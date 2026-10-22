"""Base de connaissance dans Valkey : chunks en hashes, index Valkey Search, recherches.

Comme dans la démo 1, on envoie des commandes brutes pour pouvoir afficher exactement
ce qui part vers Valkey.
"""
from __future__ import annotations

import re
import time

from .config import settings

VECTOR_FIELD = "embedding"
SCORE_ALIAS = "score"
RETURN_FIELDS = ["title", "section", "url", "source", "type", "doc_id", "text"]
# valeurs de TAG sans tiret : « - » est l'opérateur de négation du langage de requête
SOURCES = {"ovhcloud_docs": "Docs OVHcloud", "aiven_docs": "Docs Aiven", "valkey_docs": "Docs Valkey",
           "aiven_blog": "Blog Aiven", "local": "Mes documents"}

_TAG_SAFE = re.compile(r"[^a-z0-9_]")
_WORD = re.compile(r"[A-Za-zÀ-ÿ0-9]+")
STOP = set("""le la les un une des du de d l et ou en au aux pour par sur dans avec sans que qui quoi quel quelle quels
quelles est sont être avoir comment pourquoi combien est-ce ce cet cette ces mon ma mes ton ta tes son sa ses notre nos votre vos
leur leurs je tu il elle on nous vous ils elles me te se y a ai as faire fait peut peux veux the and for with what how which
are can does from this that into your you why when where but not such their then there these they was will
about use using""".split())


def tag(value: str) -> str:
    return _TAG_SAFE.sub("_", value.strip().lower())


# --------------------------------------------------------------------------- index

def create_index_args(with_text: bool = True) -> list[str]:
    s = settings
    schema: list[str] = []
    if with_text:
        schema += ["title", "TEXT", "section", "TEXT", "text", "TEXT"]
    schema += [
        "source", "TAG", "type", "TAG", "doc_id", "TAG",
        VECTOR_FIELD, "VECTOR", "HNSW", "12",
        "TYPE", "FLOAT32", "DIM", str(s.vector_dim), "DISTANCE_METRIC", "COSINE",
        "M", str(s.hnsw_m), "EF_CONSTRUCTION", str(s.hnsw_ef_construction), "EF_RUNTIME", str(s.hnsw_ef_runtime),
    ]
    return ["FT.CREATE", s.index_name, "ON", "HASH", "PREFIX", "1", s.key_prefix, "SCHEMA", *schema]


def index_exists(client) -> bool:
    try:
        client.execute_command("FT.INFO", settings.index_name)
        return True
    except Exception as exc:  # noqa: BLE001
        if re.search(r"not found|unknown|no such", str(exc).lower()):
            return False
        raise  # réseau, authentification… : ne pas masquer l'erreur derrière « index absent »


def create_index(client, drop_existing: bool = False) -> tuple[list[str], bool]:
    if index_exists(client):
        if not drop_existing:
            return [], text_enabled(client)
        client.execute_command("FT.DROPINDEX", settings.index_name)
    args = create_index_args(True)
    try:
        client.execute_command(*args)
        client.set(f"{settings.index_name}:text", "1")
        return args, True
    except Exception as exc:  # noqa: BLE001
        if not re.search(r"\btext\b|unknown|invalid|unsupported|syntax", str(exc).lower()):
            raise
        print(f"  ! FT.CREATE avec TEXT refusé ({exc}) : index sans plein texte")
        args = create_index_args(False)
        client.execute_command(*args)
        client.set(f"{settings.index_name}:text", "0")
        return args, False


def text_enabled(client) -> bool:
    return client.get(f"{settings.index_name}:text") in (b"1", "1")


def index_info(client) -> dict:
    return _pairs_to_dict(client.execute_command("FT.INFO", settings.index_name))


def num_docs(client) -> int:
    try:
        return int(float(index_info(client).get("num_docs", 0) or 0))
    except Exception:  # noqa: BLE001
        return 0


# --------------------------------------------------------------------------- requêtes

def build_filter(sources: list[str] | None) -> str:
    srcs = [t for t in (tag(s) for s in (sources or []) if s) if t]
    return "@source:{" + " | ".join(srcs) + "}" if srcs else ""


def knn_args(vec: bytes, k: int, sources: list[str] | None = None) -> list:
    filt = build_filter(sources)
    knn = f"[KNN {k} @{VECTOR_FIELD} $vec AS {SCORE_ALIAS}]"
    query = f"({filt})=>{knn}" if filt else f"*=>{knn}"
    fields = [*RETURN_FIELDS, SCORE_ALIAS]  # l'alias doit être demandé explicitement (valkey-search 1.2)
    return ["FT.SEARCH", settings.index_name, query, "PARAMS", "2", "vec", vec,
            "RETURN", str(len(fields)), *fields, "LIMIT", "0", str(k), "DIALECT", "2"]


def keywords(question: str, max_words: int = 6) -> list[str]:
    words = [w.lower() for w in _WORD.findall(question)]
    return [w for w in words if len(w) >= 3 and w not in STOP][:max_words]


def fulltext_args(question: str, k: int, sources: list[str] | None = None) -> list | None:
    """Recherche lexicale classique : tous les mots-clés de la question doivent apparaître."""
    words = keywords(question)
    if not words:
        return None
    query = " ".join(f"@text:{w}" for w in words)
    filt = build_filter(sources)
    if filt:
        query = f"{filt} {query}"
    return ["FT.SEARCH", settings.index_name, query, "RETURN", "4", "title", "section", "url", "source",
            "LIMIT", "0", str(k), "DIALECT", "2"]


def display_command(args: list) -> str:
    out = []
    for a in args:
        if isinstance(a, (bytes, bytearray)):
            out.append(f"<vecteur {len(a) // 4} x float32>")
        else:
            s = str(a)
            out.append(f'"{s}"' if any(c in s for c in ' *@{') else s)
    return " ".join(out)


# --------------------------------------------------------------------------- exécution

def _dec(v):
    if isinstance(v, (bytes, bytearray)):
        try:
            return v.decode()
        except UnicodeDecodeError:
            return None
    return v


def _pairs_to_dict(raw) -> dict:
    if isinstance(raw, dict):
        return {_dec(k): _dec(v) for k, v in raw.items()}
    out = {}
    for i in range(0, len(raw or []) - 1, 2):
        v = raw[i + 1]
        out[_dec(raw[i])] = [_dec(x) for x in v] if isinstance(v, list) else _dec(v)
    return out


def parse_reply(raw) -> tuple[int, list[dict]]:
    if not raw:
        return 0, []
    total, docs, i = int(raw[0]), [], 1
    while i < len(raw):
        key = _dec(raw[i])
        has_fields = i + 1 < len(raw) and isinstance(raw[i + 1], list)
        doc = {"key": key, **(_pairs_to_dict(raw[i + 1]) if has_fields else {})}
        if doc.get(SCORE_ALIAS) is not None:
            doc["distance"] = float(doc.pop(SCORE_ALIAS))
            doc["similarity"] = round(1 - doc["distance"], 4)
        docs.append(doc)
        i += 2 if has_fields else 1
    return total, docs


def run(client, args: list) -> dict:
    t0 = time.perf_counter()
    raw = client.execute_command(*args)
    ms = (time.perf_counter() - t0) * 1000
    total, docs = parse_reply(raw)
    return {"total": total, "results": docs, "ms": round(ms, 2), "command": display_command(args)}
