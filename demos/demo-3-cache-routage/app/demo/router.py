"""Routeur sémantique : la question est comparée à des exemples étiquetés « simple » / « complexe »
stockés dans Valkey (idx:route). Vote pondéré des k plus proches voisins.

Pas de classifieur à entraîner : corriger le routage = ajouter un exemple (HSET route:…).
"""
from __future__ import annotations

import hashlib
import time

from . import vectors
from .config import settings

LABELS = ("simple", "complex")


def ensure_index(client) -> list[str] | None:
    if vectors.index_exists(client, settings.route_index):
        return None
    return vectors.create_index(client, settings.route_index, settings.route_prefix, ["label", "TAG"])


def add_example(client, text: str, label: str, vec: bytes, origin: str = "corpus") -> str:
    if label not in LABELS:
        raise ValueError(label)
    key = settings.route_prefix + hashlib.sha1(text.encode()).hexdigest()[:12]
    client.hset(key, mapping={"text": text, "label": label, "origin": origin, "embedding": vec})
    return key


def model_for(label: str) -> str:
    return settings.simple_model if label == "simple" else settings.complex_model


def price_model_for(label: str) -> str:
    return settings.simple_price_model if label == "simple" else settings.complex_price_model


def route(client, vec: bytes) -> dict:
    res = vectors.run_knn(client, vectors.knn_args(settings.route_index, vec, settings.route_k, ["text", "label", "origin"]))
    votes = {lab: 0.0 for lab in LABELS}
    for r in res["results"]:
        if r.get("label") in votes:
            votes[r["label"]] += max(0.0, r.get("similarity", 0))
    best_sim = max((r.get("similarity", 0) for r in res["results"]), default=0)
    total = sum(votes.values()) or 1
    if best_sim < settings.route_min_similarity:
        label, reason = "complex", f"aucun exemple proche (meilleur {best_sim:.2f} < {settings.route_min_similarity}) : grand modèle par prudence"
    else:
        label = max(votes, key=votes.get)
        reason = f"vote des {len(res['results'])} plus proches exemples"
    return {**res, "votes": {k: round(v / total, 3) for k, v in votes.items()}, "label": label,
            "model": model_for(label), "reason": reason, "best": round(best_sim, 4)}


def count(client) -> dict:
    out = {}
    for lab in LABELS:
        raw = client.execute_command("FT.SEARCH", settings.route_index, f"@label:{{{lab}}}", "NOCONTENT",
                                     "LIMIT", "0", "1", "DIALECT", "2")
        out[lab] = int(raw[0]) if raw else 0
    return out
