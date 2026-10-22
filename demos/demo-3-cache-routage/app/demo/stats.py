"""Compteurs en direct dans un hash Valkey (HINCRBY / HINCRBYFLOAT) : partagés, persistants, atomiques."""
from __future__ import annotations

from .config import settings

INT_FIELDS = ["requests", "hits_exact", "hits_semantic", "calls_simple", "calls_complex",
              "tokens_used", "tokens_saved", "ms_llm", "ms_cache"]
FLOAT_FIELDS = ["cost_real", "cost_baseline"]


def record(client, **inc) -> dict:
    pipe = client.pipeline(transaction=True)
    cmds = []
    for k, v in inc.items():
        if not v:
            continue
        if k in FLOAT_FIELDS:
            pipe.hincrbyfloat(settings.stats_key, k, float(v))
            cmds.append(f"HINCRBYFLOAT {settings.stats_key} {k} {float(v):.6f}")
        else:
            pipe.hincrby(settings.stats_key, k, int(v))
            cmds.append(f"HINCRBY {settings.stats_key} {k} {int(v)}")
    pipe.execute()
    return {"commands": cmds}


def get(client) -> dict:
    raw = client.hgetall(settings.stats_key) or {}
    d = {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v) for k, v in raw.items()}
    out = {k: int(float(d.get(k, 0))) for k in INT_FIELDS}
    out.update({k: float(d.get(k, 0)) for k in FLOAT_FIELDS})
    hits = out["hits_exact"] + out["hits_semantic"]
    calls = out["calls_simple"] + out["calls_complex"]
    out["hits"] = hits
    out["hit_rate"] = round(hits / out["requests"], 3) if out["requests"] else 0
    out["cost_saved"] = round(out["cost_baseline"] - out["cost_real"], 8)
    out["avg_ms_llm"] = round(out["ms_llm"] / calls) if calls else None
    out["avg_ms_cache"] = round(out["ms_cache"] / hits, 1) if hits else None
    return out


def reset(client) -> None:
    client.delete(settings.stats_key)
