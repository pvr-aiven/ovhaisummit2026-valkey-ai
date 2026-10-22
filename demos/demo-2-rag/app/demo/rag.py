"""Pipeline RAG pas à pas. Chaque étape émet un événement affiché dans « Sous le capot »."""
from __future__ import annotations

import re
import time
from typing import Iterator

from . import history, kb, llm
from .config import settings

SYSTEM_RAG = """Tu es l'assistant technique de la démo « Valkey & IA » au Summit OVHcloud.
Règles :
- Réponds dans la langue de la question (en général le français), de façon concise : 8 phrases au plus, ou une liste courte.
- Appuie-toi UNIQUEMENT sur les extraits fournis, jamais sur une réponse précédente ni sur tes connaissances.
  Les extraits sont souvent en anglais : traduis-les.
- Chaque extrait indique sa source (Docs OVHcloud, Docs Aiven, Docs Valkey…). N'attribue jamais à un produit une
  procédure tirée d'un extrait d'un autre produit.
- Si la question cite plusieurs produits, ou n'en cite aucun alors que les extraits en couvrent plusieurs,
  réponds en une partie par produit (ex. « Sur OVHcloud : … » puis « Sur Aiven : … »).
- Cite la source de chaque affirmation avec son numéro entre crochets, par exemple [2].
- Si la réponse n'est pas dans les extraits, réponds : « Je ne trouve pas cette information dans la base de connaissance. »
- N'invente ni commande, ni syntaxe, ni chiffre, ni nom de produit. Ne donne un exemple de commande que s'il figure
  dans les extraits, recopié tel quel dans un bloc de code."""

SYSTEM_NO_RAG = "Tu es un assistant. Réponds dans la langue de la question, de façon concise (8 phrases au plus)."

NO_ANSWER = ("Je ne trouve pas cette information dans les sources autorisées : aucun extrait n'est assez proche "
             "de la question. Élargissez les sources ou reformulez.")

REWRITE = """Voici une conversation puis une nouvelle question. Réécris la nouvelle question pour qu'elle soit
compréhensible seule : remplace les « ça », « et pour… », « celui-là » par ce qu'ils désignent, et reprends
le sujet technique précis de la conversation (produit, commande, type de recherche).
Ne réponds pas à la question. Renvoie uniquement la question réécrite, sur une ligne."""


def select(found: list[dict], k: int, threshold: float, max_doc: int, max_src: int | None) -> list[dict]:
    """Choisit au plus k extraits parmi les candidats triés par similarité.

    Chaque candidat reçoit un statut : retenu, sous le seuil, ou écarté pour la diversité
    (déjà max_doc extraits de la même page, ou max_src de la même source).
    """
    kept, per_doc, per_src = [], {}, {}
    for r in found:
        sim, doc, src = r.get("similarity") or 0, r.get("doc_id") or r.get("url"), r.get("source")
        if sim < threshold:
            r["status"] = "seuil"
        elif len(kept) >= k:
            r["status"] = "au-delà de k"
        elif per_doc.get(doc, 0) >= max_doc:
            r["status"] = "même page"
        elif max_src and per_src.get(src, 0) >= max_src:
            r["status"] = "même source"
        else:
            r["status"] = "retenu"
            kept.append(r)
            per_doc[doc] = per_doc.get(doc, 0) + 1
            per_src[src] = per_src.get(src, 0) + 1
    return kept


def ev(name: str, **data) -> dict:
    return {"type": "step", "name": name, "data": data}


def build_context(results: list[dict]) -> str:
    parts = []
    for i, r in enumerate(results, 1):
        where = r.get("title", "") + (f" › {r['section']}" if r.get("section") and r.get("section") != r.get("title") else "")
        parts.append(f"[{i}] Source : {kb.SOURCES.get(r.get('source'), r.get('source'))} — {where}\n{r.get('text', '')}")
    return "\n\n".join(parts)


def history_messages(msgs: list[dict]) -> list[dict]:
    """Historique propre pour le modèle : alternance user/assistant garantie (exigée par Mistral),
    et citations [n] retirées (elles renvoyaient aux extraits d'un tour précédent)."""
    out: list[dict] = []
    for m in msgs:
        if m["role"] not in ("user", "assistant"):
            continue
        content = re.sub(r"\s*\[\d{1,2}\]", "", m["content"]) if m["role"] == "assistant" else m["content"]
        if out and out[-1]["role"] == m["role"]:
            out[-1]["content"] += "\n" + content
        else:
            out.append({"role": m["role"], "content": content})
    while out and out[0]["role"] == "assistant":
        out.pop(0)
    if out and out[-1]["role"] == "user":
        out.pop()
    return out


def ask(client, session: str, question: str, sources: list[str] | None = None,
        use_rag: bool = True, compare_fulltext: bool = False, k: int | None = None) -> Iterator[dict]:
    k = k or settings.top_k
    t_start = time.perf_counter()
    if use_rag and not kb.index_exists(client):
        from .valkey_client import describe_target
        yield {"type": "error", "message": f"L'index {settings.index_name} n'existe pas dans {describe_target()}. "
               "Lancer `make load` (puis `make check`) pour vectoriser la base et créer l'index."}
        return

    # 0. historique
    past, hinfo = history.recent(client, session)
    yield ev("history", **hinfo, messages=len(past))

    # 1. reformulation (seulement s'il y a un historique)
    standalone = question
    if use_rag and past:
        msgs = [{"role": "system", "content": REWRITE}] + history_messages(past) + \
               [{"role": "user", "content": f"Nouvelle question : {question}"}]
        standalone, info = llm.complete(msgs, max_tokens=120)
        standalone = standalone.strip().strip('"«» ') or question
        yield ev("rewrite", original=question, standalone=standalone, model=settings.chat_model, **info)

    results: list[dict] = []
    found: list[dict] = []
    if use_rag:
        # 2. embedding de la question
        t0 = time.perf_counter()
        vec = llm.embed_one(standalone)
        yield ev("embed", model=settings.embed_model, dim=int(vec.shape[0]),
                 preview=[round(float(x), 4) for x in vec[:8]], ms=round((time.perf_counter() - t0) * 1000))

        # 3. recherche vectorielle (+ filtre de source) dans Valkey
        n_cand = max(k, settings.knn_candidates)
        res = kb.run(client, kb.knn_args(llm.to_bytes(vec), n_cand, sources))
        threshold = settings.min_similarity
        found = res["results"]
        # garde-fou (seuil) + diversité (par page, et par source quand aucune source n'est imposée)
        one_source = len(sources or []) == 1
        results = select(found, k, threshold, settings.max_per_doc, None if one_source else settings.max_per_source)
        order = {id(r): i for i, r in enumerate(results, 1)}
        yield ev("search", command=res["command"], ms=res["ms"], k=k, candidates=n_cand, filters=sources or [],
                 threshold=threshold, kept=len(results), max_per_doc=settings.max_per_doc,
                 max_per_source=None if one_source else settings.max_per_source,
                 results=[{"n": order.get(id(r)), "title": r.get("title"), "section": r.get("section"), "url": r.get("url"),
                           "source": r.get("source"), "similarity": r.get("similarity"), "status": r["status"],
                           "kept": r["status"] == "retenu",
                           "excerpt": (r.get("text") or "")[:400]} for r in found])

        # 3 bis. comparaison : recherche plein texte classique sur la même question
        if compare_fulltext and kb.text_enabled(client):
            args = kb.fulltext_args(question, k, sources)
            if args:
                try:  # étape facultative : une erreur ne doit pas empêcher la réponse
                    ft = kb.run(client, args)
                    yield ev("fulltext", command=ft["command"], ms=ft["ms"], total=ft["total"],
                             keywords=kb.keywords(question),
                             results=[{"title": r.get("title"), "section": r.get("section"), "source": r.get("source")}
                                      for r in ft["results"]])
                except Exception as exc:  # noqa: BLE001
                    yield ev("fulltext", command=kb.display_command(args), ms=0, total=0,
                             keywords=kb.keywords(question), results=[], error=str(exc))

    refused = use_rag and not results
    if refused:
        # aucun extrait pertinent : on répond sans appeler le modèle, qui ne peut donc rien inventer
        best = max((r.get("similarity") or 0 for r in found), default=0)
        yield ev("guard", threshold=settings.min_similarity, best=round(best, 4), filters=sources or [])
        text = NO_ANSWER
        for piece in text.split(" "):
            yield {"type": "token", "text": piece + " "}

    # 4. prompt
    if refused:
        pass
    elif use_rag:
        user = f"Extraits de la base de connaissance :\n\n{build_context(results)}\n\nQuestion : {standalone}"
        # L'historique a déjà servi à reformuler la question : on ne le redonne PAS au modèle.
        # Sinon il recopie sa réponse précédente (ex. procédure OVHcloud) même quand les extraits
        # (ex. filtrés sur la doc Aiven) disent autre chose.
        messages = [{"role": "system", "content": SYSTEM_RAG}, {"role": "user", "content": user}]
    else:
        messages = [{"role": "system", "content": SYSTEM_NO_RAG}] + history_messages(past) + \
                   [{"role": "user", "content": question}]
    if not refused:
        prompt_words = sum(len(m["content"].split()) for m in messages)
        yield ev("prompt", messages=messages, approx_tokens=int(prompt_words * 1.4), rag=use_rag)

        # 5. génération streamée
        answer = []
        stats: dict = {}
        for piece, st in llm.stream(messages):
            if st is not None:
                stats = st
            elif piece:
                answer.append(piece)
                yield {"type": "token", "text": piece}
        text = "".join(answer).strip()
        yield ev("generate", **stats)

    # 6. sauvegarde de l'échange dans l'historique
    srcs = [{"n": i, "title": r.get("title"), "url": r.get("url"), "source": r.get("source")}
            for i, r in enumerate(results, 1)]
    a = history.append(client, session, "user", question)
    b = history.append(client, session, "assistant", text, srcs)
    yield ev("save", commands=[a["command"], b["command"]], ms=round(a["ms"] + b["ms"], 2),
             length=history.length(client, session))

    yield {"type": "done", "answer": text, "sources": srcs, "rag": use_rag,
           "total_ms": round((time.perf_counter() - t_start) * 1000)}
