"""Accès aux modèles via une API compatible OpenAI.

Le même code sert pour les trois cibles, seules l'URL, la clé et le nom du modèle changent :
  OVHcloud AI Endpoints : https://oai.endpoints.kepler.ai.cloud.ovh.net/v1
  Ollama (hors ligne)   : http://host.docker.internal:11434/v1
  Aiven AI Gateway      : URL fournie par la console Aiven (à confirmer)
"""
from __future__ import annotations

import time
from functools import lru_cache
from typing import Iterator

import numpy as np

from .config import settings


def _client(base_url: str, api_key: str, timeout: float, retries: int):
    import httpx
    from openai import OpenAI

    kwargs = {}
    if api_key in ("", "anonymous"):
        # Accès anonyme d'AI Endpoints (très limité) : il ne faut envoyer AUCUN en-tête Authorization
        def drop_auth(request):
            request.headers.pop("Authorization", None)
        kwargs["http_client"] = httpx.Client(timeout=timeout, event_hooks={"request": [drop_auth]})
    return OpenAI(base_url=base_url, api_key=api_key or "anonymous", timeout=timeout, max_retries=retries, **kwargs)


@lru_cache(maxsize=1)
def _embed_client():
    return _client(settings.embed_base_url, settings.embed_api_key, 60, 3)


@lru_cache(maxsize=1)
def _chat_client():
    return _client(settings.chat_base_url, settings.chat_api_key, 120, 2)


def embed(texts: list[str], batch: int | None = None) -> np.ndarray:
    """Vecteurs normalisés (float32). Réessaie avec attente si le quota est dépassé (HTTP 429).

    AI Endpoints accepte au plus 25 textes par appel : lots de EMBED_BATCH (16 par défaut).
    """
    batch = batch or settings.embed_batch
    from openai import RateLimitError

    out: list[list[float]] = []
    for i in range(0, len(texts), batch):
        part = texts[i:i + batch]
        for attempt in range(6):
            try:
                resp = _embed_client().embeddings.create(model=settings.embed_model, input=part,
                                                         encoding_format="float")
                out.extend(d.embedding for d in sorted(resp.data, key=lambda d: d.index))
                break
            except RateLimitError:
                wait = 10 * (attempt + 1)
                print(f"  quota atteint, nouvel essai dans {wait}s (clé API configurée ?)")
                time.sleep(wait)
        else:
            raise RuntimeError("Quota d'embeddings dépassé : configurer AI_ENDPOINTS_API_KEY")
    vecs = np.asarray(out, dtype=np.float32)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-12
    return vecs


def embed_one(text: str) -> np.ndarray:
    return embed([text])[0]


def to_bytes(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype="<f4").tobytes()


def complete(messages: list[dict], max_tokens: int = 200, temperature: float = 0.0) -> tuple[str, dict]:
    """Appel non streamé (reformulation de la question)."""
    t0 = time.perf_counter()
    resp = _chat_client().chat.completions.create(model=settings.chat_model, messages=messages,
                                                  max_tokens=max_tokens, temperature=temperature)
    usage = resp.usage.model_dump() if resp.usage else {}
    return (resp.choices[0].message.content or "").strip(), {"ms": round((time.perf_counter() - t0) * 1000), **usage}


def stream(messages: list[dict]) -> Iterator[tuple[str, dict | None]]:
    """Génération streamée : produit (morceau de texte, None) puis ("", statistiques) à la fin."""
    t0 = time.perf_counter()
    first = None
    usage: dict = {}
    n_chunks = 0
    from openai import BadRequestError, UnprocessableEntityError

    kw = dict(model=settings.chat_model, messages=messages, stream=True,
              max_tokens=settings.chat_max_tokens, temperature=settings.chat_temperature)
    try:  # demander le décompte des tokens ; certains serveurs compatibles refusent l'option
        resp = _chat_client().chat.completions.create(**kw, stream_options={"include_usage": True})
    except (BadRequestError, UnprocessableEntityError):
        resp = _chat_client().chat.completions.create(**kw)
    for ev in resp:
        if getattr(ev, "usage", None):
            usage = ev.usage.model_dump()
        if not ev.choices:
            continue
        delta = ev.choices[0].delta.content or ""
        if delta:
            if first is None:
                first = time.perf_counter()
            n_chunks += 1
            yield delta, None
    total = time.perf_counter() - t0
    out_tokens = usage.get("completion_tokens") or n_chunks
    gen_time = max(1e-3, total - ((first or time.perf_counter()) - t0))
    yield "", {
        "model": settings.chat_model,
        "first_token_ms": round(((first or time.perf_counter()) - t0) * 1000),
        "total_ms": round(total * 1000),
        "tokens_per_s": round(out_tokens / gen_time, 1),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
    }
