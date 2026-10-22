"""Cache en deux étages dans Valkey.

1. Cache exact : la question normalisée, hachée -> GET exact:<sha>. Instantané, mais rare en langage naturel.
2. Cache sémantique : KNN 1 sur l'index idx:cache. Une reformulation (« En quoi Valkey se distingue-t-il de
   Redis ? ») retrouve la réponse de « Quelle est la différence entre Valkey et Redis ? ».
Chaque entrée expire seule (EXPIRE).
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata

from . import vectors
from .config import settings

FIELDS = ["question", "answer", "model", "route", "tokens_in", "tokens_out", "cost", "llm_ms", "created"]


def normalize(q: str) -> str:
    q = unicodedata.normalize("NFKD", q.lower())
    q = "".join(c for c in q if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", q).strip()


def exact_key(q: str) -> str:
    return settings.exact_prefix + hashlib.sha1(normalize(q).encode()).hexdigest()[:16]


def ensure_index(client) -> list[str] | None:
    if vectors.index_exists(client, settings.cache_index):
        return None
    return vectors.create_index(client, settings.cache_index, settings.cache_prefix, ["model", "TAG", "route", "TAG"])


def get_exact(client, q: str) -> tuple[dict | None, dict]:
    k = exact_key(q)
    t0 = time.perf_counter()
    entry_key = client.get(k)
    entry = None
    if entry_key:
        entry_key = entry_key.decode() if isinstance(entry_key, bytes) else entry_key
        raw = client.hgetall(entry_key)
        if raw:
            entry = {vectors._d(a): vectors._d(b) for a, b in raw.items() if vectors._d(a) != "embedding"}
            entry["key"] = entry_key
    return entry, {"command": f"GET {k}", "ms": round((time.perf_counter() - t0) * 1000, 2), "hit": bool(entry)}


def get_semantic(client, vec: bytes) -> tuple[dict | None, dict]:
    res = vectors.run_knn(client, vectors.knn_args(settings.cache_index, vec, 1, FIELDS))
    best = res["results"][0] if res["results"] else None
    hit = bool(best) and best.get("similarity", 0) >= settings.cache_threshold
    return (best if hit else None), {**res, "best": best, "threshold": settings.cache_threshold, "hit": hit}


def store(client, q: str, vec: bytes, answer: str, model: str, route: str, tin: int, tout: int, cost: float,
          llm_ms: int) -> dict:
    key = settings.cache_prefix + hashlib.sha1(f"{q}{time.time()}".encode()).hexdigest()[:16]
    t0 = time.perf_counter()
    pipe = client.pipeline(transaction=False)
    pipe.hset(key, mapping={"question": q, "answer": answer, "model": model, "route": route, "tokens_in": tin,
                            "tokens_out": tout, "cost": f"{cost:.8f}", "llm_ms": llm_ms, "created": int(time.time()),
                            "embedding": vec})
    pipe.expire(key, settings.cache_ttl)
    pipe.set(exact_key(q), key, ex=settings.cache_ttl)
    pipe.execute()
    ms = (time.perf_counter() - t0) * 1000
    return {"commands": [f'HSET {key} question "{q[:50]}{"…" if len(q) > 50 else ""}" answer "…" model {model} … embedding <vecteur>',
                         f"EXPIRE {key} {settings.cache_ttl}", f"SET {exact_key(q)} {key} EX {settings.cache_ttl}"],
            "ms": round(ms, 2), "key": key}


def clear(client) -> int:
    n = 0
    for pattern in (f"{settings.cache_prefix}*", f"{settings.exact_prefix}*"):
        for k in client.scan_iter(match=pattern, count=500):
            client.delete(k)
            n += 1
    return n


def size(client) -> int:
    try:
        return vectors.num_docs(client, settings.cache_index)
    except Exception:  # noqa: BLE001
        return 0


def dump(entry: dict) -> str:
    return json.dumps({k: entry.get(k) for k in FIELDS if k in entry}, ensure_ascii=False)
