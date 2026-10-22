"""Petits utilitaires Valkey Search partagés par le cache et le routeur (commandes brutes, affichables)."""
from __future__ import annotations

import re
import time

from .config import settings

SCORE = "score"


def create_index(client, name: str, prefix: str, extra_schema: list[str]) -> list[str]:
    args = ["FT.CREATE", name, "ON", "HASH", "PREFIX", "1", prefix, "SCHEMA", *extra_schema,
            "embedding", "VECTOR", "HNSW", "10", "TYPE", "FLOAT32", "DIM", str(settings.vector_dim),
            "DISTANCE_METRIC", "COSINE", "M", str(settings.hnsw_m), "EF_CONSTRUCTION", str(settings.hnsw_ef_construction)]
    client.execute_command(*args)
    return args


def index_exists(client, name: str) -> bool:
    try:
        client.execute_command("FT.INFO", name)
        return True
    except Exception as exc:  # noqa: BLE001
        if re.search(r"not found|unknown|no such", str(exc).lower()):
            return False
        raise


def drop_index(client, name: str) -> None:
    if index_exists(client, name):
        client.execute_command("FT.DROPINDEX", name)


def num_docs(client, name: str) -> int:
    raw = client.execute_command("FT.INFO", name)
    info = _pairs(raw)
    return int(float(info.get("num_docs", 0) or 0))


def knn_args(index: str, vec: bytes, k: int, fields: list[str], filt: str = "") -> list:
    q = f"({filt})=>[KNN {k} @embedding $vec AS {SCORE}]" if filt else f"*=>[KNN {k} @embedding $vec AS {SCORE}]"
    ret = [*fields, SCORE]  # l'alias du score doit être demandé explicitement
    return ["FT.SEARCH", index, q, "PARAMS", "2", "vec", vec, "RETURN", str(len(ret)), *ret,
            "LIMIT", "0", str(k), "DIALECT", "2"]


def display(args: list) -> str:
    out = []
    for a in args:
        if isinstance(a, (bytes, bytearray)):
            out.append(f"<vecteur {len(a) // 4} x float32>")
        else:
            s = str(a)
            out.append(f'"{s}"' if any(c in s for c in " *@{") else s)
    return " ".join(out)


def _d(v):
    if isinstance(v, (bytes, bytearray)):
        try:
            return v.decode()
        except UnicodeDecodeError:
            return None
    return v


def _pairs(raw) -> dict:
    if isinstance(raw, dict):
        return {_d(k): _d(v) for k, v in raw.items()}
    return {_d(raw[i]): (_d(raw[i + 1]) if not isinstance(raw[i + 1], list) else raw[i + 1])
            for i in range(0, len(raw or []) - 1, 2)}


def run_knn(client, args: list) -> dict:
    t0 = time.perf_counter()
    raw = client.execute_command(*args)
    ms = (time.perf_counter() - t0) * 1000
    docs, i = [], 1
    while raw and i < len(raw):
        has = i + 1 < len(raw) and isinstance(raw[i + 1], list)
        d = {"key": _d(raw[i]), **(_pairs(raw[i + 1]) if has else {})}
        if d.get(SCORE) is not None:
            d["similarity"] = round(1 - float(d.pop(SCORE)), 4)
        docs.append(d)
        i += 2 if has else 1
    return {"results": docs, "ms": round(ms, 2), "command": display(args)}
