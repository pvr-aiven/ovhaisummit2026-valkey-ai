"""Test de bout en bout de l'API avec un faux Valkey en mémoire (KNN brute force).

Le faux serveur ne remplace pas un vrai test sur Valkey Search : il valide le câblage
API ↔ requêtes ↔ lecture des réponses. Le test réel se fait avec `make check`.
"""
import re

import numpy as np
import pytest

from demo import catalog, server
from demo.embeddings import to_bytes


class FakeValkey:
    def __init__(self):
        self.h = {}
        self.indexes = set()

    def hgetall(self, key):
        return dict(self.h.get(key, {}))

    def scan_iter(self, match="*", count=None):
        pre = match.rstrip("*")
        return iter([k.encode() for k in self.h if k.startswith(pre)])

    def hget(self, key, field):
        return self.h.get(key, {}).get(field.encode() if isinstance(field, str) else field)

    def _match(self, doc, filt):
        for tag, vals in re.findall(r"@(\w+):\{([^}]*)\}", filt):
            if doc[tag.encode()].decode() not in [v.strip() for v in vals.split("|")]:
                return False
        for fld, lo, hi in re.findall(r"@(\w+):\[(\S+) (\S+)\]", filt):
            v = float(doc[fld.encode()])
            lo = -np.inf if lo == "-inf" else float(lo)
            hi = np.inf if hi == "+inf" else float(hi)
            if not lo <= v <= hi:
                return False
        return True

    def execute_command(self, *args):
        cmd = args[0]
        if cmd == "FT._LIST":
            return [i.encode() for i in self.indexes]
        if cmd == "FT.INFO":
            return [b"num_docs", str(len(self.h)).encode()]
        if cmd == "HSET":
            self.h.setdefault(args[1], {})[args[2].encode()] = str(args[3]).encode()
            return 0
        if cmd == "FT.SEARCH":
            query = args[2]
            ret = (args[args.index("RETURN") + 2: args.index("RETURN") + 2 + int(args[args.index("RETURN") + 1])]
                   if "RETURN" in args else [])
            limit = int(args[args.index("LIMIT") + 2])
            m = re.match(r"^(?:\((.*)\)|\*)=>\[KNN (\d+) @embedding \$vec.*\]$", query)
            filt = m.group(1) or "" if m else query
            docs = [(k, d) for k, d in self.h.items() if self._match(d, filt)]
            if m:
                q = np.frombuffer(args[args.index("PARAMS") + 3], dtype="<f4")
                docs = sorted(((k, d, 1 - float(np.dot(q, np.frombuffer(d[b"embedding"], dtype="<f4"))))
                               for k, d in docs), key=lambda x: x[2])[:int(m.group(2))]
            else:
                docs = [(k, d, None) for k, d in docs]
            out = [len(docs)]
            if "NOCONTENT" in args:
                return out + [k.encode() for k, _, _ in docs[:limit]]
            for k, d, dist in docs[:limit]:
                fields = []
                for f in ret:
                    if f.encode() in d:  # « score » n'est pas un champ du hash
                        fields += [f.encode(), d[f.encode()]]
                if dist is not None:
                    fields += [b"score", str(dist).encode()]
                out += [k.encode(), fields]
            return out
        raise NotImplementedError(cmd)


class DirectClient:
    """Appelle directement les fonctions de route (pas besoin de httpx/TestClient)."""

    def get(self, path, params=None):
        params = params or {}
        if path == "/api/explain":
            return _Resp(server.explain_search(**params))
        if path == "/api/meta":
            return _Resp(server.meta())
        if path == "/api/browse":
            return _Resp(server.browse(**params))
        raise KeyError(path)

    def post(self, path, json=None):
        from fastapi import HTTPException
        try:
            if path == "/api/search/product":
                return _Resp(server.search_by_product(server.ProductQuery(**json)))
            if path == "/api/stock":
                return _Resp(server.set_stock(server.StockIn(**json)))
        except HTTPException as e:
            return _Resp({"detail": e.detail}, e.status_code)
        raise KeyError(path)


class _Resp:
    def __init__(self, data, status_code=200):
        self._d, self.status_code = data, status_code

    def json(self):
        return self._d


@pytest.fixture()
def api(monkeypatch):
    fake = FakeValkey()
    fake.indexes.add("idx:products")
    rng = np.random.default_rng(0)
    for i in range(30):
        v = rng.normal(size=512).astype(np.float32)
        v /= np.linalg.norm(v)
        fake.h[f"product:{i}"] = {
            b"id": str(i).encode(), b"name": f"Shoe {i}".encode(),
            b"gender": (b"women" if i % 2 else b"men"), b"category": b"sports_shoes",
            b"color": b"red", b"price": str(20 + i * 5).encode(), b"stock": str(i % 3).encode(),
            b"image": f"{i}.jpg".encode(), b"embedding": to_bytes(v),
        }
    monkeypatch.setattr(server, "get_client", lambda: fake)
    yield DirectClient(), fake


def test_meta_and_browse(api):
    c, _ = api
    assert c.get("/api/meta").json()["num_docs"] == 30
    r = c.get("/api/browse", params={"gender": "women", "price_max": 60, "count": 50}).json()
    assert r["results"] and all(d["gender"] == "women" and d["price"] <= 60 for d in r["results"])
    assert r["command"].startswith('FT.SEARCH idx:products "@gender:{women} @price:[-inf 60]"')


def test_similarity_then_hybrid_then_stock(api):
    c, _ = api
    pure = c.post("/api/search/product", json={"key": "product:4", "k": 5}).json()
    assert len(pure["results"]) == 5 and all(d["key"] != "product:4" for d in pure["results"])
    sims = [d["similarity"] for d in pure["results"]]
    assert sims == sorted(sims, reverse=True)

    flt = {"gender": "women", "price_max": 120, "in_stock": True}
    hyb = c.post("/api/search/product", json={"key": "product:4", "k": 5, "filters": flt}).json()
    assert all(d["gender"] == "women" and d["stock"] >= 1 and d["price"] <= 120 for d in hyb["results"])
    assert "=>[KNN 6 @embedding $vec AS score]" in hyb["command"]

    victim = hyb["results"][0]["key"]
    assert c.post("/api/stock", json={"key": victim, "stock": 0}).json()["command"] == f"HSET {victim} stock 0"
    after = c.post("/api/search/product", json={"key": "product:4", "k": 5, "filters": flt}).json()
    assert victim not in [d["key"] for d in after["results"]]


def test_stock_rejects_foreign_keys(api):
    c, _ = api
    assert c.post("/api/stock", json={"key": "session:1", "stock": 0}).status_code == 400


def test_explain_payload(api, monkeypatch, tmp_path):
    import dataclasses
    from demo import explain
    c, fake = api
    # catalogue + embeddings sur disque pour la projection 2D
    keys = sorted(fake.h)
    (tmp_path / "catalog.csv").write_text("id,name,gender,category,color,price,stock,image\n" + "".join(
        f"{k.split(':')[1]},n,{fake.h[k][b'gender'].decode()},Sports Shoes,red,1,1,{k.split(':')[1]}.jpg\n" for k in keys))
    np.save(tmp_path / "embeddings.npy", np.stack([np.frombuffer(fake.h[k][b"embedding"], dtype="<f4") for k in keys]))
    monkeypatch.setattr(explain, "settings", dataclasses.replace(explain.settings, data_dir=tmp_path))
    explain.projection.cache_clear()

    d = c.get("/api/explain", {"key": "product:4", "k": 5}).json()
    assert d["demo_filters"] is True and d["filters"]["gender"] == "women"
    assert len(d["product"]["vector"]) == 512 and "embedding" not in d["product"]["fields"]
    counts = [s["count"] for s in d["funnel"]]
    assert counts[0] == 30 and counts == sorted(counts, reverse=True) and len(counts) == 4
    roles = [s["role"] for s in d["segments"]]
    assert roles[:4] == ["cmd", "index", "filter", "arrow"] and "knn" in roles
    assert all(r["gender"] == "women" for r in d["hybrid"]["results"])
    pts = explain.projection()["points"]
    assert len(pts) == 30 and all(0 <= p["x"] <= 1 and 0 <= p["y"] <= 1 for p in pts)
    explain.projection.cache_clear()


def test_explain_with_user_filters(api):
    c, _ = api
    d = c.get("/api/explain", {"key": "product:3", "gender": "men", "in_stock": True, "k": 4}).json()
    assert d["demo_filters"] is False
    assert [s["label"] for s in d["funnel"]][1:] == ["genre = men", "stock ≥ 1"]
