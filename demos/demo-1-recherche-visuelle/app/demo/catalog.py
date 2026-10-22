"""Index Valkey Search, construction des requêtes hybrides et lecture des résultats.

Tout passe par des commandes Valkey brutes (FT.CREATE / FT.SEARCH / HSET) pour que
l'UI puisse afficher EXACTEMENT ce qui est envoyé au serveur pendant la démo.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from .config import settings

# Champs renvoyés pour l'affichage (l'embedding n'est jamais renvoyé : inutile et lourd)
RETURN_FIELDS = ["id", "name", "gender", "category", "color", "price", "stock", "image"]
VECTOR_FIELD = "embedding"
SCORE_ALIAS = "score"

GENDERS = ["men", "women", "unisex", "boys", "girls"]

_TAG_SAFE = re.compile(r"[^a-z0-9_]")
_WORD = re.compile(r"[A-Za-z0-9]+")


def slug(value: str) -> str:
    """Valeur de TAG sûre : minuscules, sans espace ni ponctuation (évite tout échappement)."""
    return _TAG_SAFE.sub("_", value.strip().lower()).strip("_")


# --------------------------------------------------------------------------- index

def create_index_args(with_text: bool = True) -> list[str]:
    s = settings
    schema: list[str] = []
    if with_text:
        schema += ["name", "TEXT"]
    schema += [
        "gender", "TAG",
        "category", "TAG",
        "color", "TAG",
        "price", "NUMERIC",
        "stock", "NUMERIC",
        VECTOR_FIELD, "VECTOR", "HNSW", "12",
        "TYPE", "FLOAT32",
        "DIM", str(s.vector_dim),
        "DISTANCE_METRIC", "COSINE",
        "M", str(s.hnsw_m),
        "EF_CONSTRUCTION", str(s.hnsw_ef_construction),
        "EF_RUNTIME", str(s.hnsw_ef_runtime),
    ]
    return ["FT.CREATE", s.index_name, "ON", "HASH", "PREFIX", "1", s.key_prefix, "SCHEMA", *schema]


def index_exists(client) -> bool:
    try:
        names = client.execute_command("FT._LIST") or []
        return settings.index_name.encode() in [n if isinstance(n, bytes) else str(n).encode() for n in names]
    except Exception:  # noqa: BLE001  FT._LIST (ACL @admin) peut être refusé sur un service managé
        try:
            client.execute_command("FT.INFO", settings.index_name)
            return True
        except Exception:  # noqa: BLE001
            return False


def create_index(client, drop_existing: bool = False) -> tuple[list[str], bool]:
    """Crée l'index. Retourne (commande envoyée, texte_activé).

    Si le module Search ne gère pas encore TEXT (valkey-search < 1.2), on recrée sans le champ name.
    """
    if index_exists(client):
        if not drop_existing:
            return [], True
        client.execute_command("FT.DROPINDEX", settings.index_name)
    args = create_index_args(with_text=True)
    try:
        client.execute_command(*args)
        return args, True
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if not re.search(r"\btext\b", msg) and not re.search(r"unknown|invalid|unsupported|syntax", msg):
            raise
        print(f"  ! FT.CREATE avec TEXT refusé ({exc}) : nouvel essai sans le champ name")
        args = create_index_args(with_text=False)
        client.execute_command(*args)
        return args, False


def index_info(client) -> dict:
    raw = client.execute_command("FT.INFO", settings.index_name)
    return _pairs_to_dict(raw)


# --------------------------------------------------------------------------- requêtes

@dataclass
class Filters:
    gender: str | None = None
    categories: list[str] = field(default_factory=list)
    price_min: float | None = None
    price_max: float | None = None
    in_stock: bool = False
    text: str | None = None

    def is_empty(self) -> bool:
        return not (self.gender or self.categories or self.price_min is not None
                    or self.price_max is not None or self.in_stock or self.text)


def _num(v: float | None, default: str) -> str:
    if v is None:
        return default
    return str(int(v)) if float(v).is_integer() else str(v)


def build_filter(f: Filters) -> str:
    """Construit l'expression de filtre Valkey Search (vide si aucun filtre)."""
    parts: list[str] = []
    if f.gender:
        parts.append(f"@gender:{{{slug(f.gender)}}}")
    cats = [slug(c) for c in f.categories if c]
    if cats:
        parts.append("@category:{" + " | ".join(cats) + "}")
    if f.price_min is not None or f.price_max is not None:
        parts.append(f"@price:[{_num(f.price_min, '-inf')} {_num(f.price_max, '+inf')}]")
    if f.in_stock:
        parts.append("@stock:[1 +inf]")
    if f.text:
        words = _WORD.findall(f.text)[:5]
        if words:
            parts.extend(f"@name:{w.lower()}" for w in words)
    return " ".join(parts)


def build_knn_query(f: Filters, k: int, ef_runtime: int | None = None) -> str:
    filt = build_filter(f)
    ef = f" EF_RUNTIME {ef_runtime}" if ef_runtime else ""
    knn = f"[KNN {k} @{VECTOR_FIELD} $vec{ef} AS {SCORE_ALIAS}]"
    return f"({filt})=>{knn}" if filt else f"*=>{knn}"


def knn_search_args(f: Filters, vec_bytes: bytes, k: int, ef_runtime: int | None = None) -> list:
    query = build_knn_query(f, k, ef_runtime)
    # Avec RETURN, valkey-search ne renvoie la distance que si son alias est demandé explicitement
    fields = [*RETURN_FIELDS, SCORE_ALIAS]
    return [
        "FT.SEARCH", settings.index_name, query,
        "PARAMS", "2", "vec", vec_bytes,
        "RETURN", str(len(fields)), *fields,
        "LIMIT", "0", str(k),
        "DIALECT", "2",
    ]


def browse_args(f: Filters, offset: int, count: int) -> list:
    # Une requête non vectorielle a besoin d'un filtre : sans filtre, on prend "tous les prix".
    query = build_filter(f) or "@price:[-inf +inf]"
    return [
        "FT.SEARCH", settings.index_name, query,
        "RETURN", str(len(RETURN_FIELDS)), *RETURN_FIELDS,
        "LIMIT", str(offset), str(count),
        "DIALECT", "2",
    ]


def display_command(args: list) -> str:
    """Rend la commande lisible : le vecteur binaire est remplacé par un libellé."""
    out = []
    for a in args:
        if isinstance(a, (bytes, bytearray)):
            out.append(f"<vecteur {len(a) // 4} x float32>")
        else:
            s = str(a)
            out.append(f'"{s}"' if (" " in s or "*" in s or "@" in s) else s)
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
    out = {}
    if isinstance(raw, dict):
        return {_dec(k): _dec(v) if not isinstance(v, list) else v for k, v in raw.items()}
    for i in range(0, len(raw or []) - 1, 2):
        k, v = _dec(raw[i]), raw[i + 1]
        out[k] = [_dec(x) for x in v] if isinstance(v, list) else _dec(v)
    return out


def parse_search_reply(raw) -> tuple[int, list[dict]]:
    """Réponse RESP2 de FT.SEARCH : [total, key1, [champ, valeur, ...], key2, [...], ...]."""
    if not raw:
        return 0, []
    total = int(raw[0])
    docs = []
    i = 1
    while i < len(raw):
        key = _dec(raw[i])
        fields = raw[i + 1] if i + 1 < len(raw) and isinstance(raw[i + 1], list) else []
        doc = {"key": key, **_pairs_to_dict(fields)}
        for num in ("price", "stock"):
            if doc.get(num) is not None:
                try:
                    doc[num] = float(doc[num]) if num == "price" else int(float(doc[num]))
                except ValueError:
                    pass
        if doc.get(SCORE_ALIAS) is not None:
            dist = float(doc[SCORE_ALIAS])
            doc["distance"] = dist
            doc["similarity"] = round(1.0 - dist, 4)  # COSINE : distance = 1 - similarité
            del doc[SCORE_ALIAS]
        docs.append(doc)
        i += 2 if (i + 1 < len(raw) and isinstance(raw[i + 1], list)) else 1
    return total, docs


def run(client, args: list) -> dict:
    t0 = time.perf_counter()
    raw = client.execute_command(*args)
    ms = (time.perf_counter() - t0) * 1000
    total, docs = parse_search_reply(raw)
    return {"total": total, "results": docs, "latency_ms": round(ms, 2), "command": display_command(args)}


def get_vector(client, key: str) -> bytes | None:
    return client.hget(key, VECTOR_FIELD)


def set_stock(client, key: str, stock: int) -> dict:
    args = ["HSET", key, "stock", str(int(stock))]
    t0 = time.perf_counter()
    client.execute_command(*args)
    return {"command": display_command(args), "latency_ms": round((time.perf_counter() - t0) * 1000, 2)}


# --------------------------------------------------------------------------- pédagogie (onglet « Comment ça marche »)

def filter_steps(f: Filters) -> list[tuple[str, str]]:
    """Filtres cumulés, un critère à la fois : [(libellé, expression cumulée), ...]."""
    steps: list[tuple[str, str]] = []
    acc = Filters()
    if f.gender:
        acc.gender = f.gender
        steps.append((f"genre = {slug(f.gender)}", build_filter(acc)))
    if f.categories:
        acc.categories = list(f.categories)
        steps.append(("type = " + " ou ".join(slug(c) for c in f.categories), build_filter(acc)))
    if f.price_min is not None or f.price_max is not None:
        acc.price_min, acc.price_max = f.price_min, f.price_max
        steps.append((f"prix entre {_num(f.price_min, '-∞')} et {_num(f.price_max, '+∞')} €", build_filter(acc)))
    if f.in_stock:
        acc.in_stock = True
        steps.append(("stock ≥ 1", build_filter(acc)))
    return steps


def count(client, filter_expr: str) -> int:
    """Nombre de documents qui satisfont un filtre (le total ne dépend pas de LIMIT)."""
    raw = client.execute_command("FT.SEARCH", settings.index_name, filter_expr or "@price:[-inf +inf]",
                                 "NOCONTENT", "LIMIT", "0", "1", "DIALECT", "2")
    return int(raw[0]) if raw else 0


def query_segments(f: Filters, k: int, dim: int) -> list[dict]:
    """Découpe la commande FT.SEARCH en morceaux commentés, dans l'ordre d'écriture."""
    filt = build_filter(f)
    seg = [
        {"text": "FT.SEARCH", "role": "cmd", "label": "Commande", "explain": "Rechercher dans un index Valkey Search."},
        {"text": settings.index_name, "role": "index", "label": "Index",
         "explain": "L'index créé par FT.CREATE sur toutes les clés product:*."},
    ]
    if filt:
        seg.append({"text": f'"({filt})', "role": "filter", "label": "Pré-filtre",
                    "explain": "Ne garder que les produits qui respectent les règles métier (index TAG et NUMERIC)."})
    else:
        seg.append({"text": '"*', "role": "filter", "label": "Pas de filtre",
                    "explain": "* = tous les produits sont candidats : similarité pure."})
    seg += [
        {"text": "=>", "role": "arrow", "label": "Puis",
         "explain": "Sur les candidats retenus, lancer la recherche vectorielle."},
        {"text": f"[KNN {k}", "role": "knn", "label": f"KNN {k}",
         "explain": f"Les {k} plus proches voisins (k-nearest neighbors)."},
        {"text": f"@{VECTOR_FIELD}", "role": "field", "label": "Champ vecteur",
         "explain": "Comparer avec le champ embedding de chaque produit (index HNSW)."},
        {"text": "$vec", "role": "param", "label": "Vecteur requête",
         "explain": "Le vecteur de la chaussure de référence, passé en paramètre."},
        {"text": f'AS {SCORE_ALIAS}]"', "role": "score", "label": "Score",
         "explain": "Nommer « score » la distance cosinus renvoyée (0 = identique)."},
        {"text": "PARAMS 2 vec", "role": "param", "label": "Paramètres",
         "explain": "Valeur de $vec : les octets du vecteur."},
        {"text": f"<{dim} x float32>", "role": "param", "label": "Vecteur",
         "explain": f"{dim} nombres de 4 octets = {dim * 4} octets envoyés au serveur."},
        {"text": f"RETURN {len(RETURN_FIELDS) + 1} " + " ".join(RETURN_FIELDS), "role": "return", "label": "Champs",
         "explain": "Ne renvoyer que ces champs (pas l'embedding, inutile côté interface)."},
        {"text": SCORE_ALIAS, "role": "score", "label": "Score demandé",
         "explain": "Demander aussi la distance calculée, sous le nom choisi dans AS score."},
        {"text": f"LIMIT 0 {k}", "role": "limit", "label": "Pagination", "explain": f"Au plus {k} résultats."},
        {"text": "DIALECT 2", "role": "dialect", "label": "Syntaxe",
         "explain": "Active la syntaxe de requête vectorielle =>[KNN …]."},
    ]
    return seg
