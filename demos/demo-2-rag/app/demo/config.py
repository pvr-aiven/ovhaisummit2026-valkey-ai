"""Configuration de la démo 2, lue depuis les variables d'environnement (env/<cible>.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return value if value not in (None, "") else default


@dataclass(frozen=True)
class Settings:
    target: str = _env("DEMO_TARGET", "local")

    # Valkey
    valkey_url: str = _env("VALKEY_URL", "valkey://localhost:6379")
    valkey_ca_cert: str | None = _env("VALKEY_CA_CERT")
    index_name: str = _env("INDEX_NAME", "idx:kb")
    key_prefix: str = _env("KEY_PREFIX", "chunk:")
    history_prefix: str = _env("HISTORY_PREFIX", "chat:")
    history_ttl: int = int(_env("HISTORY_TTL", "3600"))      # une conversation expire après 1 h d'inactivité
    history_turns: int = int(_env("HISTORY_TURNS", "6"))     # nombre de messages repris pour le contexte

    # API compatibles OpenAI : AI Endpoints (OVHcloud), Ollama (hors ligne), AI Gateway (Aiven)
    embed_base_url: str = _env("EMBED_BASE_URL", "https://oai.endpoints.kepler.ai.cloud.ovh.net/v1")
    embed_api_key: str = _env("EMBED_API_KEY", _env("AI_ENDPOINTS_API_KEY", "anonymous"))
    embed_model: str = _env("EMBED_MODEL", "bge-m3")
    vector_dim: int = int(_env("VECTOR_DIM", "1024"))
    embed_batch: int = int(_env("EMBED_BATCH", "16"))   # AI Endpoints : 25 textes maximum par appel

    chat_base_url: str = _env("CHAT_BASE_URL", "https://oai.endpoints.kepler.ai.cloud.ovh.net/v1")
    chat_api_key: str = _env("CHAT_API_KEY", _env("AI_ENDPOINTS_API_KEY", "anonymous"))
    chat_model: str = _env("CHAT_MODEL", "Mistral-Small-3.2-24B-Instruct-2506")
    chat_temperature: float = float(_env("CHAT_TEMPERATURE", "0.2"))
    chat_max_tokens: int = int(_env("CHAT_MAX_TOKENS", "700"))

    # Récupération
    top_k: int = int(_env("TOP_K", "5"))
    # Garde-fou : un extrait moins similaire que ce seuil n'est pas donné au modèle (0 = désactivé)
    min_similarity: float = float(_env("MIN_SIMILARITY", "0.60"))
    # Diversité : on demande plus de candidats à Valkey, puis on limite les extraits par document et par source,
    # pour qu'une question sur « OVHcloud et Aiven » ne soit pas monopolisée par une seule page
    knn_candidates: int = int(_env("KNN_CANDIDATES", "15"))
    max_per_doc: int = int(_env("MAX_PER_DOC", "2"))
    max_per_source: int = int(_env("MAX_PER_SOURCE", "3"))
    hnsw_m: int = int(_env("HNSW_M", "16"))
    hnsw_ef_construction: int = int(_env("HNSW_EF_CONSTRUCTION", "200"))
    hnsw_ef_runtime: int = int(_env("HNSW_EF_RUNTIME", "64"))

    # Découpage (en mots ; 1 mot ≈ 1,3 token en anglais)
    chunk_words: int = int(_env("CHUNK_WORDS", "300"))
    chunk_overlap: int = int(_env("CHUNK_OVERLAP", "40"))

    # Données
    data_dir: Path = Path(_env("DATA_DIR", "/data"))
    sources_file: Path = Path(_env("SOURCES_FILE", "/srv/sources.yaml"))

    @property
    def corpus_dir(self) -> Path:
        return self.data_dir / "corpus"

    @property
    def chunks_file(self) -> Path:
        return self.data_dir / "chunks.jsonl"

    @property
    def embeddings_file(self) -> Path:
        return self.data_dir / "embeddings.npy"


settings = Settings()
