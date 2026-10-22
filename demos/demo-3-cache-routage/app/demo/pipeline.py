"""Une question, pas à pas : cache exact → embedding → cache sémantique → routage → modèle → mise en cache.

Chaque étape émet un événement affiché dans le panneau « Sous le capot ».

Économies (affichées en direct) :
  coût de référence = tout envoyer au grand modèle, sans cache, avec les tokens observés ;
  coût réel         = ce qui a vraiment été payé (0 pour une réponse servie par le cache).
C'est une estimation prudente : un modèle de raisonnement produirait en réalité plus de tokens.
"""
from __future__ import annotations

import time
from typing import Iterator

from . import cache, llm, prices, router, stats
from .config import settings

SYSTEM = ("Tu es l'assistant technique de la démo « Valkey & IA ». Réponds en français, clairement et sans "
          "remplissage. Pour une question simple : quelques phrases. Pour une question complexe : structure ta "
          "réponse (étapes, listes) et reste concis.")


def ev(name: str, **data) -> dict:
    return {"type": "step", "name": name, "data": data}


def _num(v, default=0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def serve_from_cache(client, entry: dict, kind: str, t_start: float, extra: dict | None = None) -> Iterator[dict]:
    tin, tout = int(_num(entry.get("tokens_in"))), int(_num(entry.get("tokens_out")))
    table = prices.load()
    baseline = prices.cost(settings.complex_price_model, tin, tout, table)
    ms = round((time.perf_counter() - t_start) * 1000, 1)
    st = stats.record(client, requests=1, **{f"hits_{kind}": 1}, tokens_saved=tin + tout,
                      cost_baseline=baseline, ms_cache=ms)
    yield ev("stats", **st)
    yield {"type": "done", "source": f"cache {'exact' if kind == 'exact' else 'sémantique'}", "answer": entry.get("answer", ""),
           "model": entry.get("model"), "route": entry.get("route"), "latency_ms": ms,
           "original_question": entry.get("question"), "original_llm_ms": int(_num(entry.get("llm_ms"))),
           "similarity": (extra or {}).get("similarity"), "tokens": tin + tout, "cost": 0.0,
           "valkey_ms": (extra or {}).get("valkey_ms"), "embed_ms": (extra or {}).get("embed_ms"),
           "saved": round(baseline, 8), "stats": stats.get(client)}


def ask(client, question: str, use_cache: bool = True, use_router: bool = True) -> Iterator[dict]:
    t_start = time.perf_counter()
    q = question.strip()

    # 1. cache exact : la même question, au caractère près (normalisée)
    if use_cache:
        entry, info = cache.get_exact(client, q)
        yield ev("exact", **info)
        if entry:
            yield from serve_from_cache(client, entry, "exact", t_start, {"valkey_ms": info["ms"]})
            return

    # 2. vecteur de la question (un seul embedding, réutilisé par le cache et le routeur)
    t0 = time.perf_counter()
    vec = llm.embed_one(q)
    vb = llm.to_bytes(vec)
    embed_ms = round((time.perf_counter() - t0) * 1000)
    yield ev("embed", model=settings.embed_model, dim=int(vec.shape[0]), ms=embed_ms)

    # 3. cache sémantique : une question proche a-t-elle déjà une réponse ?
    if use_cache:
        entry, info = cache.get_semantic(client, vb)
        best = info.get("best") or {}
        yield ev("semantic", command=info["command"], ms=info["ms"], hit=info["hit"], threshold=info["threshold"],
                 similarity=best.get("similarity"), matched=best.get("question"))
        if entry:
            yield from serve_from_cache(client, entry, "semantic", t_start,
                                        {"similarity": entry.get("similarity"), "valkey_ms": info["ms"], "embed_ms": embed_ms})
            return

    # 4. routage : petit ou grand modèle ?
    if use_router:
        r = router.route(client, vb)
        label = r["label"]
        yield ev("route", command=r["command"], ms=r["ms"], label=label, model=r["model"], votes=r["votes"],
                 reason=r["reason"], neighbors=[{"text": n.get("text"), "label": n.get("label"),
                                                 "similarity": n.get("similarity"), "origin": n.get("origin")}
                                                for n in r["results"]])
    else:
        label = "complex"
        yield ev("route", label=label, model=router.model_for(label), votes={}, reason="routage désactivé : tout va au grand modèle",
                 neighbors=[], ms=0, command="")
    model = router.model_for(label)

    # 5. génération streamée (avec la « réflexion » des modèles de raisonnement)
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": q}]
    answer, st = [], {}
    max_tokens = settings.max_tokens_simple if label == "simple" else settings.max_tokens_complex
    for kind, payload in llm.stream(model, messages, max_tokens):
        if kind == "content":
            answer.append(payload)
            yield {"type": "token", "text": payload}
        elif kind == "reasoning":
            yield {"type": "reasoning", "text": payload}
        else:
            st = payload
    text = "".join(answer).strip()
    tin, tout = st.get("prompt_tokens", 0), st.get("completion_tokens", 0)
    table = prices.load()
    real = prices.cost(router.price_model_for(label), tin, tout, table)
    baseline = prices.cost(settings.complex_price_model, tin, tout, table)
    yield ev("generate", **st, label=label, cost=round(real, 8), price_model=router.price_model_for(label))

    # 6. mise en cache (hash + vecteur + TTL) pour les prochaines fois
    if use_cache and text:
        info = cache.store(client, q, vb, text, model, label, tin, tout, real, st.get("total_ms", 0))
        yield ev("store", **info)

    # 7. compteurs
    s = stats.record(client, requests=1, **{f"calls_{label}": 1}, tokens_used=tin + tout,
                     cost_real=real, cost_baseline=baseline, ms_llm=st.get("total_ms", 0))
    yield ev("stats", **s)
    yield {"type": "done", "source": "modèle", "answer": text, "model": model, "route": label,
           "latency_ms": round((time.perf_counter() - t_start) * 1000), "tokens": tin + tout,
           "cost": round(real, 8), "saved": round(baseline - real, 8), "stats": stats.get(client)}
