"""Tests sans réseau : cache exact et sémantique, routage, compteurs et prix (modèles simulés)."""
import dataclasses

import numpy as np
import pytest

from demo import cache, llm, pipeline, prices, router, stats
from fake_valkey import FakeValkey

DIM = 1024
rng = np.random.default_rng(0)
BASE = {name: rng.normal(size=DIM) for name in ("valkey_redis", "memcached", "delete_key", "architecture", "port")}


def vec_for(text: str) -> np.ndarray:
    """Vecteurs simulés : les reformulations partagent la même base (similarité ~0,97)."""
    t = text.lower()
    if "memcached" in t:
        v = 0.7 * BASE["valkey_redis"] + 0.7 * BASE["memcached"]
    elif "redis" in t:
        v = BASE["valkey_redis"] + 0.25 * rng.normal(size=DIM)
    elif "supprimer" in t or "effacer" in t:
        v = BASE["delete_key"] + 0.3 * rng.normal(size=DIM)
    elif "port" in t:
        v = BASE["port"] + 0.3 * rng.normal(size=DIM)
    else:
        v = BASE["architecture"] + 0.3 * rng.normal(size=DIM)
    v = v.astype(np.float32)
    return v / np.linalg.norm(v)


@pytest.fixture()
def env(monkeypatch, tmp_path):
    client = FakeValkey()
    cache.ensure_index(client)
    router.ensure_index(client)
    for text, label in [("Comment supprimer une clé dans Valkey ?", "simple"), ("Quel port utilise Valkey ?", "simple"),
                        ("Quelle est la différence entre Valkey et Redis ?", "simple"),
                        ("Conçois une architecture multi-tenant avec observabilité", "complex"),
                        ("Rédige un plan de migration détaillé avec calendrier", "complex")]:
        router.add_example(client, text, label, llm.to_bytes(vec_for(text)))
    calls = []
    monkeypatch.setattr(llm, "embed_one", vec_for)

    def stream(model, messages, max_tokens):
        calls.append(model)
        if "oss" in model:
            yield "reasoning", "Je réfléchis…"
        for t in ["Réponse ", "de ", model]:
            yield "content", t
        yield "stats", {"model": model, "first_token_ms": 300, "total_ms": 2500 if "oss" in model else 900,
                        "prompt_tokens": 100, "completion_tokens": 400 if "oss" in model else 120, "usage_reported": True}

    monkeypatch.setattr(llm, "stream", stream)
    monkeypatch.setattr(prices, "load", lambda: dict(prices.DEFAULT_PRICES))
    return client, calls


def names(evs):
    return [e.get("name") or e["type"] for e in evs]


def test_first_question_calls_model_then_exact_then_semantic_hit(env):
    client, calls = env
    q1 = "Quelle est la différence entre Valkey et Redis ?"
    evs = list(pipeline.ask(client, q1))
    assert names(evs)[:4] == ["exact", "embed", "semantic", "route"] and "store" in names(evs)
    done = evs[-1]
    assert done["source"] == "modèle" and done["route"] == "simple" and calls == ["Mistral-Small-3.2-24B-Instruct-2506"]
    assert done["cost"] == pytest.approx(prices.cost("Mistral-Small-3.2-24B-Instruct-2506", 100, 120), rel=1e-3)

    evs = list(pipeline.ask(client, "quelle est la différence entre valkey et redis"))       # même question, normalisée
    assert names(evs)[0] == "exact" and evs[-1]["source"] == "cache exact" and len(calls) == 1

    evs = list(pipeline.ask(client, "En quoi Valkey se distingue-t-il de Redis ?"))          # reformulation
    sem = next(e for e in evs if e.get("name") == "semantic")["data"]
    assert sem["hit"] and sem["similarity"] >= 0.90 and evs[-1]["source"] == "cache sémantique" and len(calls) == 1
    assert evs[-1]["original_question"] == q1 and evs[-1]["cost"] == 0.0 and evs[-1]["saved"] > 0

    s = stats.get(client)
    assert s["requests"] == 3 and s["hits"] == 2 and s["tokens_saved"] == 440 and s["cost_saved"] > 0


def test_neighbour_question_below_threshold_goes_to_model(env):
    client, calls = env
    list(pipeline.ask(client, "Quelle est la différence entre Valkey et Redis ?"))
    evs = list(pipeline.ask(client, "Quelle est la différence entre Valkey et Memcached ?"))
    sem = next(e for e in evs if e.get("name") == "semantic")["data"]
    assert not sem["hit"] and 0.5 < sem["similarity"] < 0.9 and evs[-1]["source"] == "modèle" and len(calls) == 2


def test_complex_question_routed_to_reasoning_model(env):
    client, calls = env
    evs = list(pipeline.ask(client, "Conçois une architecture de cache multi-région avec plan de reprise"))
    r = next(e for e in evs if e.get("name") == "route")["data"]
    assert r["label"] == "complex" and r["votes"]["complex"] > r["votes"]["simple"]
    assert calls == ["gpt-oss-120b"] and any(e["type"] == "reasoning" for e in evs)
    assert evs[-1]["saved"] == 0  # déjà sur le grand modèle : rien d'économisé par le routage


def test_router_disabled_sends_everything_to_big_model_and_cache_disabled(env):
    client, calls = env
    evs = list(pipeline.ask(client, "Comment supprimer une clé dans Valkey ?", use_cache=False, use_router=False))
    assert "exact" not in names(evs) and "store" not in names(evs) and calls == ["gpt-oss-120b"]


def test_unknown_question_goes_to_big_model_by_prudence(env, monkeypatch):
    client, _ = env
    monkeypatch.setattr(router, "settings", dataclasses.replace(router.settings, route_min_similarity=0.99))
    evs = list(pipeline.ask(client, "Comment supprimer une clé dans Valkey ?", use_cache=False))
    r = next(e for e in evs if e.get("name") == "route")["data"]
    assert r["label"] == "complex" and "prudence" in r["reason"]


def test_teach_adds_example(env):
    client, _ = env
    before = router.count(client)["simple"]
    router.add_example(client, "Quelle heure est-il ?", "simple", llm.to_bytes(vec_for("port")), origin="appris")
    assert router.count(client)["simple"] == before + 1


def test_parse_prices_fr():
    html = """<div><div id="ai-endpoints"></div><table>
      <tr><th>Modèle</th><th>Prix ( HT / 1M tokens en entrée)</th><th>Prix ( HT / 1M tokens en sortie)</th></tr>
      <tr><td>gpt-oss-120b</td><td>0,08 €</td><td>0,40 €</td></tr><tr><td>bge-m3</td><td>0,01 €</td><td>-</td></tr>
      <tr><td>Qwen3Guard-Gen-8B</td><td>Gratuit</td><td>Gratuit</td></tr></table>
      <table><tr><th>Modèle</th><th>Prix ( HT / heure)</th></tr><tr><td>whisper-large-v3</td><td>0,147 €</td></tr></table></div>"""
    p = prices.parse_prices(html)
    assert p["gpt-oss-120b"] == (0.08, 0.40) and p["bge-m3"] == (0.01, 0.0) and p["Qwen3Guard-Gen-8B"] == (0.0, 0.0)
    assert "whisper-large-v3" not in p
    assert prices.cost("gpt-oss-120b", 1_000_000, 1_000_000, p) == pytest.approx(0.48)


def test_normalize_for_exact_cache():
    assert cache.exact_key("Quelle est la différence entre Valkey et Redis ?") == cache.exact_key("quelle est la difference entre valkey et redis")


def test_trace_replays_first_pass_without_calling_model(env, monkeypatch):
    from demo import server
    client, calls = env
    monkeypatch.setattr(server, "get_client", lambda: client)
    q = "Quelle est la différence entre Valkey et Redis ?"
    list(pipeline.ask(client, q))
    n_calls = len(calls)
    t = server.trace(q)                                   # par défaut : comme la première fois
    assert t["already_cached"] and not t["exact"]["hit"] and all(cache.normalize(x["question"]) != t["normalized"]
                                                                 for x in t["semantic"]["neighbors"])
    assert t["route"]["label"] == "simple" and len(t["route"]["neighbors"]) == 5 and len(t["embed"]["preview"]) == 96
    assert server.trace(q, ignore_same=False)["exact"]["hit"]
    t2 = server.trace("En quoi Valkey se distingue-t-il de Redis ?")
    assert t2["semantic"]["neighbors"][0]["similarity"] >= 0.9
    assert len(calls) == n_calls                           # aucun appel au modèle de génération
