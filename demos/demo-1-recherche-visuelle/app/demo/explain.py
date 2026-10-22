"""Données de l'onglet « Comment ça marche » : vecteur réel, hash, entonnoir de filtres, projection 2D."""
from __future__ import annotations

import csv
from functools import lru_cache

import numpy as np

from . import catalog
from .config import settings
from .embeddings import from_bytes

DEMO_FILTERS = catalog.Filters(gender="women", price_max=100, in_stock=True)


@lru_cache(maxsize=1)
def projection() -> dict:
    """Projection 2D (ACP) des embeddings du catalogue, calculée une fois au premier appel."""
    if not settings.embeddings_file.exists():
        return {"points": [], "variance": 0.0}
    vecs = np.load(settings.embeddings_file).astype(np.float32)
    with open(settings.catalog_csv, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    rows = rows[: len(vecs)]
    centered = vecs - vecs.mean(axis=0)
    _, s, vt = np.linalg.svd(centered, full_matrices=False)
    xy = centered @ vt[:2].T
    xy = (xy - xy.min(axis=0)) / (xy.max(axis=0) - xy.min(axis=0) + 1e-9)  # normalisé dans [0, 1]
    variance = float((s[:2] ** 2).sum() / (s ** 2).sum())
    points = [{
        "key": f"{settings.key_prefix}{r['id']}",
        "x": round(float(x), 4), "y": round(float(y), 4),
        "category": catalog.slug(r["category"]), "gender": catalog.slug(r["gender"]),
        "image": r["image"],
    } for r, (x, y) in zip(rows, xy)]
    return {"points": points, "variance": round(variance, 3)}


def product_view(client, key: str) -> dict | None:
    raw = client.hgetall(key)
    if not raw:
        return None
    blob = raw.get(catalog.VECTOR_FIELD.encode(), b"")
    fields = {k.decode(): v.decode() for k, v in raw.items() if k != catalog.VECTOR_FIELD.encode()}
    vec = from_bytes(blob)
    return {
        "key": key,
        "fields": fields,
        "vector": [round(float(x), 4) for x in vec],
        "vector_bytes": len(blob),
        "vector_norm": round(float(np.linalg.norm(vec)), 4),
    }


def funnel(client, f: catalog.Filters, total: int) -> list[dict]:
    out = [{"label": "tout le catalogue", "filter": "*", "count": total}]
    for label, expr in catalog.filter_steps(f):
        out.append({"label": label, "filter": expr, "count": catalog.count(client, expr)})
    return out
