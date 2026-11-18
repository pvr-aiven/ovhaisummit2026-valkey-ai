"""Tests sans réseau : découpage, requêtes Valkey, historique et pipeline RAG complet (modèles simulés)."""
import hashlib

import numpy as np
import pytest

from demo import history, ingest, kb, llm, rag
from demo.load import embedding_input
from fake_valkey import FakeValkey

DIM = 1024


def fake_vec(text: str) -> np.ndarray:
    """Vecteur déterministe : sac de mots haché, pour que des textes proches soient proches."""
    v = np.zeros(DIM, dtype=np.float32)
    for w in text.lower().split():
        v[int(hashlib.md5(w.encode()).hexdigest(), 16) % DIM] += 1
    return v / (np.linalg.norm(v) + 1e-9)


# --------------------------------------------------------------------------- ingestion

def test_clean_markdown_front_matter_bom_links():
    raw = '﻿---\ntitle: "Hashes"\n---\n> For AI agents: index\n\n# Hashes\nSee [the docs](https://x) ![img](a.png)\n'
    title, text = ingest.clean_markdown(raw)
    assert title == "Hashes" and "For AI agents" not in text and "See the docs" in text and "img" not in text


def test_split_and_pack_keep_code_blocks_and_overlap():
    text = "# A\nintro " * 1 + "\n## B\n```\n# pas un titre\n```\n" + "\n\n".join(["mot " * 120] * 4)
    secs = ingest.split_sections(text)
    assert any("# pas un titre" in b for _, b in secs) and secs[-1][0] == "A › B"
    pieces = ingest.pack(secs[-1][1], 300, 40)
    assert len(pieces) >= 2 and all(len(p.split()) <= 340 for p in pieces)


def test_chunk_doc_merges_short_sections():
    d = ingest.Doc("d1", "u", "valkey-docs", "doc", "T", "# T\n## Court\nDeux mots.\n## Long\n" + "texte " * 80)
    chunks = ingest.chunk_doc(d, 300, 40)
    assert len(chunks) == 1 and "Deux mots." in chunks[0].text and chunks[0].id == "d1:0"


def test_html_to_markdown():
    html = "<html><body><nav>menu</nav><article><h1>Titre</h1><p>Para.</p><ul><li>un</li></ul><p>Loading code...</p></article></body></html>"
    title, text = ingest.html_to_markdown(html)
    assert title == "Titre" and "menu" not in text and "- un" in text and "Loading" not in text


# --------------------------------------------------------------------------- requêtes

def test_knn_args_filter_and_score():
    args = kb.knn_args(b"\0" * DIM * 4, 5, ["ovhcloud-docs", "aiven_blog"])
    assert args[2] == "(@source:{ovhcloud_docs | aiven_blog})=>[KNN 5 @embedding $vec AS score]"
    r = args.index("RETURN")
    assert args[r + 1 + int(args[r + 1])] == "score"
    assert "<vecteur 1024 x float32>" in kb.display_command(args)


def test_fulltext_keywords_drop_stopwords():
    assert kb.keywords("Comment créer un index vectoriel dans Valkey ?") == ["créer", "index", "vectoriel", "valkey"]
    args = kb.fulltext_args("Comment créer un index vectoriel ?", 5)
    assert args[2] == "@text:créer @text:index @text:vectoriel"


def test_create_index_args():
    a = kb.create_index_args()
    assert a[a.index("HNSW") + 1] == "12" and "1024" in a and "TEXT" in a
    assert "TEXT" not in kb.create_index_args(False)


# --------------------------------------------------------------------------- pipeline

@pytest.fixture()
def env(monkeypatch):
    client = FakeValkey()
    kb.create_index(client)
    docs = [
        ("vk:0", "Valkey Search - Overview", "Indexes", "valkey_docs", "FT.CREATE creates an index with VECTOR fields HNSW"),
        ("vk:1", "Valkey Search - Queries", "Hybrid", "valkey_docs", "hybrid query filter tag numeric KNN vector"),
        ("ovh:0", "AI Endpoints - Getting started", "Models", "ovhcloud_docs", "embedding models bge-m3 available on AI Endpoints"),
        ("blog:0", "Index your Valkey Cache", "", "aiven_blog", "index your cache with HNSW vector search"),
    ]
    for cid, title, section, source, text in docs:
        c = {"title": title, "section": section, "text": text}
        client.hset(f"chunk:{cid}", {"doc_id": cid.split(":")[0], "url": f"https://x/{cid}", "source": source,
                                     "type": "doc", "title": title, "section": section, "text": text, "position": 0,
                                     "embedding": llm.to_bytes(fake_vec(embedding_input(c)))})
    import dataclasses
    monkeypatch.setattr(rag, "settings", dataclasses.replace(rag.settings, min_similarity=0.0))
    calls = {"complete": 0, "stream": []}
    monkeypatch.setattr(llm, "embed_one", lambda t: fake_vec(t))

    def complete(msgs, max_tokens=200, temperature=0.0):
        calls["complete"] += 1
        return "Comment régler la précision HNSW de la recherche vectorielle dans Valkey ?", {"ms": 12}

    def stream(msgs):
        calls["stream"].append(msgs)
        for t in ["Utilisez ", "FT.CREATE ", "[1]."]:
            yield t, None
        yield "", {"model": "m", "first_token_ms": 5, "total_ms": 20, "tokens_per_s": 50.0,
                   "prompt_tokens": 100, "completion_tokens": 3}

    monkeypatch.setattr(llm, "complete", complete)
    monkeypatch.setattr(llm, "stream", stream)
    return client, calls


def test_full_rag_flow_then_follow_up(env):
    client, calls = env
    evs = list(rag.ask(client, "s1234", "Comment créer un index vectoriel HNSW ?", compare_fulltext=True))
    names = [e.get("name") or e["type"] for e in evs]
    assert names == ["history", "embed", "search", "fulltext", "prompt", "token", "token", "token", "generate", "save", "done"]
    search = next(e for e in evs if e.get("name") == "search")["data"]
    assert "hnsw" in search["results"][0]["excerpt"].lower() and "similarity" in search["results"][0]
    sims = [r["similarity"] for r in search["results"]]
    assert sims == sorted(sims, reverse=True)
    prompt = next(e for e in evs if e.get("name") == "prompt")["data"]["messages"]
    assert "[1]" in prompt[-1]["content"] and prompt[0]["role"] == "system"
    done = evs[-1]
    assert done["answer"] == "Utilisez FT.CREATE [1]." and done["sources"][0]["n"] == 1
    assert history.length(client, "s1234") == 2

    # question de suivi : reformulée grâce à l'historique, et l'historique est passé au modèle
    evs2 = list(rag.ask(client, "s1234", "Et pour régler la précision ?"))
    rw = next(e for e in evs2 if e.get("name") == "rewrite")["data"]
    assert calls["complete"] == 1 and "précision" in rw["standalone"]
    # l'historique sert à la reformulation, mais n'est pas redonné au modèle avec les extraits
    roles = [m["role"] for m in calls["stream"][-1]]
    assert roles == ["system", "user"] and "précision" in calls["stream"][-1][-1]["content"]
    assert history.length(client, "s1234") == 4


def test_source_filter(env):
    client, _ = env
    evs = list(rag.ask(client, "s5678", "embedding models", sources=["ovhcloud_docs"]))
    res = next(e for e in evs if e.get("name") == "search")["data"]["results"]
    assert res and all(r["source"] == "ovhcloud_docs" for r in res)


def test_no_rag_skips_retrieval(env):
    client, calls = env
    evs = list(rag.ask(client, "s9999", "Qu'est-ce que Valkey ?", use_rag=False))
    names = {e.get("name") for e in evs}
    assert "search" not in names and "embed" not in names
    assert calls["stream"][-1][-1]["content"] == "Qu'est-ce que Valkey ?"
    assert evs[-1]["sources"] == []


def test_fulltext_finds_nothing_for_french_question(env):
    client, _ = env
    evs = list(rag.ask(client, "s4321", "Comment créer un index vectoriel ?", compare_fulltext=True))
    ft = next(e for e in evs if e.get("name") == "fulltext")["data"]
    assert ft["total"] == 0


def test_history_rejects_bad_session(env):
    client, _ = env
    with pytest.raises(ValueError):
        history.key("../../etc")


def test_history_messages_alternate_and_drop_citations():
    msgs = [{"role": "assistant", "content": "orphelin"}, {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "r1 [1] et [2]."}, {"role": "user", "content": "q2"}]
    out = rag.history_messages(msgs)
    assert [m["role"] for m in out] == ["user", "assistant"] and out[1]["content"] == "r1 et."


def test_pack_keeps_code_fence_whole_and_order():
    body = "intro " * 20 + "\n\n```\nFT.SEARCH idx\n\nFT.INFO idx\n```\n\n" + "long " * 400
    pieces = ingest.pack(body, 300, 40)
    assert pieces[0].startswith("intro") and pieces[0].count("```") == 2


def test_xadd_display_keeps_content_field(env):
    client, _ = env
    shown = history.append(client, "s7777", "user", "bonjour")["command"]
    assert shown.startswith('XADD chat:s7777 "*" role user content bonjour')


def test_missing_index_gives_clear_error(env):
    client, _ = env
    client.index = None
    evs = list(rag.ask(client, "s1111", "Comment créer un index ?"))
    assert evs[-1]["type"] == "error" and "make load" in evs[-1]["message"]


def test_guard_refuses_without_calling_model(env, monkeypatch):
    import dataclasses
    client, calls = env
    monkeypatch.setattr(rag, "settings", dataclasses.replace(rag.settings, min_similarity=0.99))
    n_before = len(calls["stream"])
    evs = list(rag.ask(client, "s2222", "Comment me connecter en Python ?", sources=["aiven_blog"]))
    names = [e.get("name") or e["type"] for e in evs]
    assert "guard" in names and "prompt" not in names and "generate" not in names
    assert len(calls["stream"]) == n_before                       # aucun appel au modèle
    assert evs[-1]["answer"] == rag.NO_ANSWER and evs[-1]["sources"] == []
    search = next(e for e in evs if e.get("name") == "search")["data"]
    assert search["kept"] == 0 and all(r["kept"] is False for r in search["results"])


def test_dedupe_drops_boilerplate_and_duplicates():
    mk = lambda i, sec, txt: ingest.Chunk(f"d:{i}", "d", "u", "s", "doc", "T", sec, txt, i)
    out = ingest.dedupe([mk(0, "T › Objective", "texte utile"), mk(1, "T › Feedback", "Please send us your questions"),
                         mk(2, "U › Intro", "texte  utile"), mk(3, "T › We want your feedback!", "x")])
    assert [c.id for c in out] == ["d:0"]


def test_clean_markdown_aiven_anchors():
    raw = "> For the complete documentation index, see [llms.txt](/docs/llms.txt).\n\n# Titre<!-- --><!-- -->\n## Valkey Search[\u200b](#valkey-search \"Direct link to Valkey Search\")\ntexte\n"
    title, text = ingest.clean_markdown(raw)
    assert title == "Titre" and "## Valkey Search\n" in text + "\n" and "Direct link" not in text and "llms.txt" not in text


def test_price_table_rows_become_sentences():
    html = """<div><div id="ai-endpoints"></div><h3>AI Endpoints</h3><h3>LLM</h3><table>
      <tr><th>Model</th><th>Price ( excl. VAT / 1M input tokens)</th><th>Price ( excl. VAT / 1M output tokens)</th></tr>
      <tr><td>Mistral-Small-3.2-24B-Instruct-2506</td><td>$0.10</td><td>$0.31</td></tr>
      <tr><td>bge-m3</td><td>$0.01</td><td>-</td></tr></table></div>"""
    title, text = ingest.html_section_to_markdown(html, "ai-endpoints")
    assert title == "AI Endpoints"
    assert "- Mistral-Small-3.2-24B-Instruct-2506 : Price (excl. VAT / 1M input tokens): $0.10; Price (excl. VAT / 1M output tokens): $0.31." in text
    assert "- bge-m3 : Price (excl. VAT / 1M input tokens): $0.01." in text


def test_catalog_to_markdown_one_section_per_model():
    models = [{"id": "bge-m3", "name": "bge-m3", "category": "Embeddings", "description": "Multilingual.",
               "metadata": {"publishing_information": {"publisher": "BAAI", "licence_name": "MIT"},
                            "model_specs": {"capabilities": {"batch": True, "input_modality": ["text"], "output_modality": ["embedding_vector"]},
                                            "model_parameters": {"params": {"context_size": 8192, "output_dimension": 1024, "max_batch_size": 25}}}}}]
    title, text = ingest.catalog_to_markdown(models)
    secs = ingest.split_sections(text)
    assert secs[-1][0] == f"{title} › bge-m3" and "1024" in secs[-1][1] and "25 textes" in secs[-1][1]


def test_clean_markdown_strips_mdx_tags_but_not_syntax_placeholders():
    raw = 'Go to <code className="action">Public Cloud</code> > <ManagerLink to="/x">Databases</ManagerLink>\n`<filter>=>[KNN <K> @f $p]`'
    _, text = ingest.clean_markdown(raw)
    assert "Go to Public Cloud > Databases" in text and "`<filter>=>[KNN <K> @f $p]`" in text


def test_select_diversifies_by_page_and_source():
    mk = lambda sim, doc, src: {"similarity": sim, "doc_id": doc, "source": src}
    found = [mk(.74, "a1", "aiven_docs"), mk(.71, "a1", "aiven_docs"), mk(.70, "a1", "aiven_docs"),
             mk(.68, "o1", "ovhcloud_docs"), mk(.67, "a2", "aiven_docs"), mk(.66, "a3", "aiven_docs"),
             mk(.65, "o2", "ovhcloud_docs"), mk(.50, "o3", "ovhcloud_docs")]
    kept = rag.select(found, 5, 0.60, 2, 3)
    assert [r["doc_id"] for r in kept] == ["a1", "a1", "o1", "a2", "o2"]
    assert found[2]["status"] == "même page" and found[5]["status"] == "même source" and found[7]["status"] == "seuil"
    # une seule source imposée : pas de plafond par source
    assert [r["doc_id"] for r in rag.select([dict(r) for r in found[:6]], 5, 0.60, 2, None)] == ["a1", "a1", "o1", "a2", "a3"]


# --------------------------------------------------------------------------- reformulation (questions qui s'entremêlent)

def test_needs_rewrite_only_for_follow_ups():
    assert not rag.needs_rewrite("Comment créer un index vectoriel dans Valkey ?")
    assert not rag.needs_rewrite("Comment créer un index vectoriel ?")
    assert rag.needs_rewrite("Et avec plusieurs valeurs de tag ?")
    assert rag.needs_rewrite("Comment je fais ça sur Aiven ?")
    assert rag.needs_rewrite("Et sur OVHcloud ?") and rag.needs_rewrite("Pourquoi ?")


def test_check_rewrite_rejects_answers_and_product_swaps():
    q = "Et pour la configurer ?"
    assert rag.check_rewrite(q, "Je ne trouve pas cette information dans la base de connaissance.")[1]
    assert rag.check_rewrite(q, "") == (q, "reformulation vide")
    q2 = "Comment créer un index vectoriel dans Valkey ?"
    assert rag.check_rewrite(q2, "Comment créer un index vectoriel dans Elasticsearch ?")[0] == q2   # produit perdu
    past = [{"role": "user", "content": "Comment créer un index vectoriel dans Valkey ?"}]
    assert rag.check_rewrite("Et ça marche sur Aiven ?", "Valkey Search marche-t-il sur Aiven et Elasticsearch ?", past)[1]
    ok = rag.check_rewrite("Et sur Aiven ?", "Comment créer un index vectoriel Valkey sur Aiven ?", past)
    assert ok == ("Comment créer un index vectoriel Valkey sur Aiven ?", None)


def test_rewrite_prompt_is_a_transcript_without_refusals():
    past = [{"role": "user", "content": "Et pour Elasticsearch ?"},
            {"role": "assistant", "content": "Je ne trouve pas cette information dans la base de connaissance."}]
    msgs = rag.rewrite_messages(past, "Et sur Aiven ?")
    assert [m["role"] for m in msgs] == ["system", "user"]
    assert "Utilisateur : Et pour Elasticsearch ?" in msgs[1]["content"] and "Je ne trouve" not in msgs[1]["content"]


def test_standalone_question_after_other_topic_is_not_rewritten(env):
    client, calls = env
    list(rag.ask(client, "s5678", "Est-ce qu'Elasticsearch fait de la recherche hybride ?"))
    evs = list(rag.ask(client, "s5678", "Comment créer un index vectoriel dans Valkey ?"))
    rw = next(e for e in evs if e.get("name") == "rewrite")["data"]
    assert rw["skipped"] and rw["standalone"] == "Comment créer un index vectoriel dans Valkey ?"
    assert calls["complete"] == 0
    assert "Elasticsearch" not in calls["stream"][-1][-1]["content"].split("Question :")[-1]


def test_bad_rewrite_falls_back_to_original_question(env, monkeypatch):
    client, calls = env
    list(rag.ask(client, "s9012", "Comment créer un index vectoriel HNSW ?"))
    monkeypatch.setattr(llm, "complete", lambda *a, **k: ("Je ne trouve pas cette information.", {"ms": 3}))
    evs = list(rag.ask(client, "s9012", "Et pour régler la précision ?"))
    rw = next(e for e in evs if e.get("name") == "rewrite")["data"]
    assert rw["standalone"] == "Et pour régler la précision ?" and "répondu" in rw["rejected"]
