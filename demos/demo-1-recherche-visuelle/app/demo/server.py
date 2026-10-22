"""API + interface web de la démo 1 (recherche visuelle et hybride)."""
from __future__ import annotations

import csv
import io
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image

try:  # photos iPhone (HEIC) glissées depuis Photos / AirDrop
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:  # pragma: no cover
    pass
from pydantic import BaseModel, Field

from . import catalog, explain
from .config import settings
from .embeddings import embed_image, embed_text, to_bytes, warmup
from .valkey_client import describe_target, get_client

STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    warmup()  # charge les modèles au démarrage, pas pendant la première requête sur scène
    yield


app = FastAPI(title="Démo 1 – Recherche visuelle et hybride avec Valkey", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class FilterIn(BaseModel):
    gender: str | None = None
    categories: list[str] = Field(default_factory=list)
    price_min: float | None = None
    price_max: float | None = None
    in_stock: bool = False
    text: str | None = None

    def to_filters(self) -> catalog.Filters:
        return catalog.Filters(**self.model_dump())


class ProductQuery(BaseModel):
    key: str
    k: int = 12
    filters: FilterIn = Field(default_factory=FilterIn)


class TextQuery(BaseModel):
    text: str
    k: int = 12
    filters: FilterIn = Field(default_factory=FilterIn)


class StockIn(BaseModel):
    key: str
    stock: int


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/comment-ca-marche")
def explain_page() -> FileResponse:
    return FileResponse(STATIC / "explain.html")


@app.get("/images/{name}")
def image(name: str) -> FileResponse:
    path = (settings.images_dir / name).resolve()
    if settings.images_dir.resolve() not in path.parents or not path.exists():
        raise HTTPException(404)
    return FileResponse(path)


@app.get("/api/meta")
def meta() -> dict:
    client = get_client()
    categories: dict[str, str] = {}
    if settings.catalog_csv.exists():
        with open(settings.catalog_csv, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                categories[catalog.slug(r["category"])] = r["category"]
    info = catalog.index_info(client) if catalog.index_exists(client) else {}
    return {
        "target": settings.target,
        "valkey": describe_target(),
        "index": settings.index_name,
        "num_docs": int(float(info.get("num_docs", 0) or 0)),
        "categories": sorted(categories.items(), key=lambda kv: kv[1]),
        "genders": catalog.GENDERS,
        "image_model": settings.image_model,
    }


def _filters_from_query(gender, category, price_min, price_max, in_stock, q) -> catalog.Filters:
    return catalog.Filters(
        gender=gender or None,
        categories=[c for c in (category or "").split(",") if c],
        price_min=price_min, price_max=price_max,
        in_stock=in_stock, text=q or None,
    )


@app.get("/api/browse")
def browse(gender: str | None = None, category: str | None = None, price_min: float | None = None,
           price_max: float | None = None, in_stock: bool = False, q: str | None = None,
           offset: int = 0, count: int = 24) -> dict:
    f = _filters_from_query(gender, category, price_min, price_max, in_stock, q)
    return catalog.run(get_client(), catalog.browse_args(f, offset, count))


def _knn(vec: bytes, f: catalog.Filters, k: int, exclude: str | None = None) -> dict:
    client = get_client()
    res = catalog.run(client, catalog.knn_search_args(f, vec, k + (1 if exclude else 0)))
    if exclude:
        res["results"] = [d for d in res["results"] if d["key"] != exclude][:k]
    return res


@app.post("/api/search/product")
def search_by_product(q: ProductQuery) -> dict:
    vec = catalog.get_vector(get_client(), q.key)
    if not vec:
        raise HTTPException(404, f"{q.key} introuvable")
    return _knn(vec, q.filters.to_filters(), q.k, exclude=q.key)


@app.post("/api/search/image")
def search_by_image(file: UploadFile = File(...), filters: str = Form("{}"), k: int = Form(12)) -> dict:
    try:
        img = Image.open(io.BytesIO(file.file.read()))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Image illisible : {exc}") from exc
    vec = to_bytes(embed_image(img))
    return _knn(vec, FilterIn(**json.loads(filters)).to_filters(), k)


@app.post("/api/search/text")
def search_by_text(q: TextQuery) -> dict:
    return _knn(to_bytes(embed_text(q.text)), q.filters.to_filters(), q.k)


@app.post("/api/stock")
def set_stock(s: StockIn) -> dict:
    if not s.key.startswith(settings.key_prefix):
        raise HTTPException(400, "clé invalide")
    return catalog.set_stock(get_client(), s.key, s.stock)


@app.get("/api/product/{key}")
def product(key: str) -> dict:
    view = explain.product_view(get_client(), key)
    if not view:
        raise HTTPException(404, f"{key} introuvable")
    view.pop("vector")
    return view


@app.get("/api/space")
def space() -> dict:
    """Projection 2D de tous les embeddings du catalogue (ACP)."""
    return explain.projection()


@app.get("/api/explain")
def explain_search(key: str | None = None, gender: str | None = None, category: str | None = None,
                   price_min: float | None = None, price_max: float | None = None, in_stock: bool = False,
                   k: int = 8) -> dict:
    """Tout ce qu'il faut pour raconter UNE recherche hybride, avec les vraies données."""
    client = get_client()
    f = _filters_from_query(gender, category, price_min, price_max, in_stock, None)
    demo_filters = f.is_empty()
    if demo_filters:  # aucun filtre transmis : exemple parlant pour le public
        f = explain.DEMO_FILTERS
    if not key:
        pts = explain.projection()["points"]
        key = pts[len(pts) // 3]["key"] if pts else next(client.scan_iter(match=f"{settings.key_prefix}*"), b"").decode()
    product = explain.product_view(client, key)
    if not product:
        raise HTTPException(404, f"{key} introuvable")
    vec = catalog.get_vector(client, key)
    info = catalog.index_info(client)
    total = int(float(info.get("num_docs", 0) or 0))
    return {
        "product": product,
        "filters": {"gender": f.gender, "categories": f.categories, "price_min": f.price_min,
                    "price_max": f.price_max, "in_stock": f.in_stock},
        "demo_filters": demo_filters,
        "num_docs": total,
        "dim": settings.vector_dim,
        "hnsw": {"m": settings.hnsw_m, "ef_construction": settings.hnsw_ef_construction,
                 "ef_runtime": settings.hnsw_ef_runtime},
        "schema": catalog.display_command(catalog.create_index_args()),
        "funnel": explain.funnel(client, f, total),
        "segments": catalog.query_segments(f, k, settings.vector_dim),
        "pure": _knn(vec, catalog.Filters(), k, exclude=key),
        "hybrid": _knn(vec, f, k, exclude=key),
    }
