"""Configuration de la démo, lue depuis les variables d'environnement (.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return value if value not in (None, "") else default


@dataclass(frozen=True)
class Settings:
    # Cible : local | ovh | aiven (informatif, affiché dans l'UI)
    target: str = _env("DEMO_TARGET", "local")

    # Connexion Valkey : valkey://host:port (local) ou rediss://user:pass@host:port (TLS, OVH / Aiven)
    valkey_url: str = _env("VALKEY_URL", "valkey://localhost:6379")
    # Certificat CA optionnel (OVH fournit un CA à télécharger dans le Control Panel)
    valkey_ca_cert: str | None = _env("VALKEY_CA_CERT")

    # Index et préfixe des clés
    index_name: str = _env("INDEX_NAME", "idx:products")
    key_prefix: str = _env("KEY_PREFIX", "product:")

    # Modèles d'embedding (open source, exécutés dans le conteneur)
    image_model: str = _env("IMAGE_MODEL", "clip-ViT-B-32")
    text_model: str = _env("TEXT_MODEL", "sentence-transformers/clip-ViT-B-32-multilingual-v1")
    vector_dim: int = int(_env("VECTOR_DIM", "512"))

    # Paramètres HNSW
    hnsw_m: int = int(_env("HNSW_M", "16"))
    hnsw_ef_construction: int = int(_env("HNSW_EF_CONSTRUCTION", "200"))
    hnsw_ef_runtime: int = int(_env("HNSW_EF_RUNTIME", "64"))

    # Données
    data_dir: Path = Path(_env("DATA_DIR", "/data"))
    max_products: int = int(_env("MAX_PRODUCTS", "3000"))

    @property
    def images_dir(self) -> Path:
        return self.data_dir / "images"

    @property
    def catalog_csv(self) -> Path:
        return self.data_dir / "catalog.csv"

    @property
    def embeddings_file(self) -> Path:
        return self.data_dir / "embeddings.npy"


settings = Settings()
