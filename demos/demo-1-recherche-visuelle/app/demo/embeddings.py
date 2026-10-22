"""Embeddings d'images (CLIP) et de texte multilingue aligné sur CLIP.

Les deux modèles produisent des vecteurs de 512 dimensions dans le même espace :
on peut donc chercher une image avec une autre image OU avec une phrase en français.
Les modèles sont open source et tournent dans le conteneur (CPU suffit).
"""
from __future__ import annotations

from functools import lru_cache
from typing import Iterable

import numpy as np
from PIL import Image, ImageOps

from .config import settings


@lru_cache(maxsize=1)
def _image_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(settings.image_model, device="cpu")


@lru_cache(maxsize=1)
def _text_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(settings.text_model, device="cpu")


def _to_rgb(img: Image.Image) -> Image.Image:
    img = ImageOps.exif_transpose(img)  # photos de téléphone : appliquer l'orientation EXIF
    return img.convert("RGB") if img.mode != "RGB" else img


def embed_images(images: Iterable[Image.Image], batch_size: int = 64) -> np.ndarray:
    vecs = _image_model().encode(
        [_to_rgb(i) for i in images],
        batch_size=batch_size,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    return vecs.astype(np.float32)


def embed_image(img: Image.Image) -> np.ndarray:
    return embed_images([img])[0]


def embed_text(text: str) -> np.ndarray:
    vec = _text_model().encode([text], normalize_embeddings=True, convert_to_numpy=True)[0]
    return vec.astype(np.float32)


def to_bytes(vec: np.ndarray) -> bytes:
    """Format attendu par Valkey Search : float32 little-endian."""
    return np.asarray(vec, dtype="<f4").tobytes()


def from_bytes(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype="<f4")


def warmup() -> None:
    """Télécharge et charge les modèles (à lancer AVANT de monter sur scène)."""
    embed_image(Image.new("RGB", (64, 64), "white"))
    embed_text("chaussure")
