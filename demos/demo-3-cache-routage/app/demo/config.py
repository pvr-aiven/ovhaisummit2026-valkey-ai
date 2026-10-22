"""Configuration de la démo 3, lue depuis les variables d'environnement (env/<cible>.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return value if value not in (None, "") else default


AI_ENDPOINTS = "https://oai.endpoints.kepler.ai.cloud.ovh.net/v1"


@dataclass(frozen=True)
class Settings:
    target: str = _env("DEMO_TARGET", "local")

    # Valkey
    valkey_url: str = _env("VALKEY_URL", "valkey://localhost:6379")
    valkey_ca_cert: str | None = _env("VALKEY_CA_CERT")
    cache_index: str = _env("CACHE_INDEX", "idx:cache")
    cache_prefix: str = _env("CACHE_PREFIX", "cache:")
    exact_prefix: str = _env("EXACT_PREFIX", "exact:")
    route_index: str = _env("ROUTE_INDEX", "idx:route")
    route_prefix: str = _env("ROUTE_PREFIX", "route:")
    stats_key: str = _env("STATS_KEY", "stats:demo3")
    cache_ttl: int = int(_env("CACHE_TTL", "86400"))           # une réponse en cache vit 24 h

    # Embeddings (API compatible OpenAI)
    embed_base_url: str = _env("EMBED_BASE_URL", AI_ENDPOINTS)
    embed_api_key: str = _env("EMBED_API_KEY", _env("AI_ENDPOINTS_API_KEY", "anonymous"))
    embed_model: str = _env("EMBED_MODEL", "bge-m3")
    vector_dim: int = int(_env("VECTOR_DIM", "1024"))

    # Deux modèles : « simple » (petit, rapide, économique) et « complexe » (gros modèle de raisonnement)
    chat_base_url: str = _env("CHAT_BASE_URL", AI_ENDPOINTS)
    chat_api_key: str = _env("CHAT_API_KEY", _env("AI_ENDPOINTS_API_KEY", "anonymous"))
    simple_model: str = _env("SIMPLE_MODEL", "Mistral-Small-3.2-24B-Instruct-2506")
    complex_model: str = _env("COMPLEX_MODEL", "gpt-oss-120b")
    # Modèles dont le prix est utilisé pour le compteur (utile hors ligne : on chiffre « comme sur AI Endpoints »)
    simple_price_model: str = _env("SIMPLE_PRICE_MODEL", _env("SIMPLE_MODEL", "Mistral-Small-3.2-24B-Instruct-2506"))
    complex_price_model: str = _env("COMPLEX_PRICE_MODEL", _env("COMPLEX_MODEL", "gpt-oss-120b"))
    max_tokens_simple: int = int(_env("MAX_TOKENS_SIMPLE", "500"))
    max_tokens_complex: int = int(_env("MAX_TOKENS_COMPLEX", "2500"))

    # Seuils (similarité cosinus BGE-M3, mesurés : reformulations 0,94-0,98 ; question voisine 0,71)
    cache_threshold: float = float(_env("CACHE_THRESHOLD", "0.90"))
    route_k: int = int(_env("ROUTE_K", "5"))
    route_min_similarity: float = float(_env("ROUTE_MIN_SIMILARITY", "0.45"))

    hnsw_m: int = int(_env("HNSW_M", "16"))
    hnsw_ef_construction: int = int(_env("HNSW_EF_CONSTRUCTION", "200"))

    data_dir: Path = Path(_env("DATA_DIR", "/data"))
    routes_file: Path = Path(_env("ROUTES_FILE", "/srv/routes.yaml"))

    @property
    def prices_file(self) -> Path:
        return self.data_dir / "prices.json"


settings = Settings()
