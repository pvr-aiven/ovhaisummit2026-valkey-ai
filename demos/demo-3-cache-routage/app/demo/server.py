"""API + interface web de la démo 3 (cache sémantique et routage)."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import cache, llm, pipeline, prices, router, stats, vectors
from .config import settings
from .valkey_client import describe_target, get_client

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="Démo 3 – Cache et routage sémantiques avec Valkey")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    use_cache: bool = True
    use_router: bool = True


class TeachIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    label: str


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/meta")
def meta() -> dict:
    client = get_client()
    ready = vectors.index_exists(client, settings.cache_index) and vectors.index_exists(client, settings.route_index)
    table = prices.load()
    return {
        "target": settings.target, "valkey": describe_target(), "ready": ready,
        "embed_model": settings.embed_model,
        "simple_model": settings.simple_model, "complex_model": settings.complex_model,
        "simple_price": table.get(settings.simple_price_model), "complex_price": table.get(settings.complex_price_model),
        "simple_price_model": settings.simple_price_model, "complex_price_model": settings.complex_price_model,
        "cache_threshold": settings.cache_threshold, "cache_size": cache.size(client) if ready else 0,
        "routes": router.count(client) if ready else {}, "llm_host": settings.chat_base_url.split("//")[-1].split("/")[0],
        "stats": stats.get(client),
    }


@app.post("/api/ask")
def ask(q: AskIn) -> StreamingResponse:
    client = get_client()

    def events():
        try:
            for e in pipeline.ask(client, q.question, q.use_cache, q.use_router):
                yield f"data: {json.dumps(e, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001
            yield f"data: {json.dumps({'type': 'error', 'message': f'{type(exc).__name__}: {exc}'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/api/stats")
def get_stats() -> dict:
    client = get_client()
    return {**stats.get(client), "cache_size": cache.size(client)}


@app.post("/api/reset")
def reset(what: str = "all") -> dict:
    client = get_client()
    out = {}
    if what in ("all", "cache"):
        out["cache_deleted"] = cache.clear(client)
    if what in ("all", "stats"):
        stats.reset(client)
        out["stats"] = "reset"
    return out


@app.post("/api/teach")
def teach(t: TeachIn) -> dict:
    """Correction du routage en direct : la question devient un nouvel exemple étiqueté."""
    if t.label not in router.LABELS:
        raise HTTPException(400, "label = simple | complex")
    client = get_client()
    key = router.add_example(client, t.question, t.label, llm.to_bytes(llm.embed_one(t.question)), origin="appris")
    return {"key": key, "command": f'HSET {key} text "{t.question[:50]}…" label {t.label} origin appris embedding <vecteur>',
            "routes": router.count(client)}


@app.get("/comment-ca-marche")
def explain_page() -> FileResponse:
    return FileResponse(STATIC / "explain.html")


@app.get("/api/trace")
def trace(q: str, ignore_same: bool = True) -> dict:
    """Parcourt la cascade SANS appeler le modèle de génération : de quoi l'expliquer avec les vraies valeurs."""
    import time as _t

    client = get_client()
    q = q.strip()
    if not q:
        raise HTTPException(400, "question vide")
    out: dict = {"question": q, "normalized": cache.normalize(q)}
    entry, info = cache.get_exact(client, q)
    # par défaut, on rejoue la question « comme la première fois » : sa propre réponse en cache est ignorée
    out["already_cached"] = bool(entry)
    if ignore_same and entry:
        info = {**info, "hit": False}
        entry = None
    out["ignore_same"] = ignore_same
    out["exact"] = {**info, "key": cache.exact_key(q), "entry_question": (entry or {}).get("question")}
    t0 = _t.perf_counter()
    vec = llm.embed_one(q)
    vb = llm.to_bytes(vec)
    out["embed"] = {"model": settings.embed_model, "dim": int(vec.shape[0]), "ms": round((_t.perf_counter() - t0) * 1000),
                    "preview": [round(float(x), 4) for x in vec[:96]]}
    sem = vectors.run_knn(client, vectors.knn_args(settings.cache_index, vb, 4, ["question", "model", "route"]))
    neigh = [r for r in sem["results"] if not (ignore_same and cache.normalize(r.get("question") or "") == out["normalized"])]
    out["semantic"] = {"command": sem["command"], "ms": sem["ms"], "threshold": settings.cache_threshold,
                       "neighbors": [{"question": r.get("question"), "model": r.get("model"), "similarity": r.get("similarity")}
                                     for r in neigh[:3]]}
    r = router.route(client, vb)
    out["route"] = {"command": r["command"], "ms": r["ms"], "k": settings.route_k, "min_similarity": settings.route_min_similarity,
                    "neighbors": [{"text": n.get("text"), "label": n.get("label"), "similarity": n.get("similarity"),
                                   "origin": n.get("origin")} for n in r["results"]],
                    "votes": r["votes"], "label": r["label"], "reason": r["reason"], "best": r["best"]}
    table = prices.load()
    out["models"] = {lab: {"model": router.model_for(lab), "price_model": router.price_model_for(lab),
                           "price": table.get(router.price_model_for(lab))} for lab in router.LABELS}
    out["cache_ttl"] = settings.cache_ttl
    return out
