"""Appels de modèles via une API compatible OpenAI (AI Endpoints, Ollama, AI Gateway Aiven)."""
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
    if api_key in ("", "anonymous"):  # accès anonyme AI Endpoints : aucun en-tête Authorization
        def drop_auth(request):
            request.headers.pop("Authorization", None)
        kwargs["http_client"] = httpx.Client(timeout=timeout, event_hooks={"request": [drop_auth]})
    return OpenAI(base_url=base_url, api_key=api_key or "anonymous", timeout=timeout, max_retries=retries, **kwargs)


@lru_cache(maxsize=1)
def _embed_client():
    return _client(settings.embed_base_url, settings.embed_api_key, 60, 3)


@lru_cache(maxsize=1)
def _chat_client():
    return _client(settings.chat_base_url, settings.chat_api_key, 180, 1)


def _unreachable(base_url: str, exc: Exception) -> RuntimeError:
    hint = ("Ollama est-il lancé sur le portable (`ollama list`) ? Un VPN actif peut aussi bloquer "
            "host.docker.internal depuis Docker." if "11434" in base_url or "host.docker.internal" in base_url
            else "Connexion Internet / proxy ? Clé AI Endpoints dans env/secrets.env ?")
    return RuntimeError(f"Impossible de joindre {base_url} ({exc.__cause__ or exc}). {hint}")


def embed(texts: list[str], batch: int = 16) -> np.ndarray:
    from openai import APIConnectionError, RateLimitError

    out = []
    for i in range(0, len(texts), batch):
        for attempt in range(6):
            try:
                r = _embed_client().embeddings.create(model=settings.embed_model, input=texts[i:i + batch],
                                                      encoding_format="float")
                out.extend(d.embedding for d in sorted(r.data, key=lambda d: d.index))
                break
            except RateLimitError:
                time.sleep(10 * (attempt + 1))
            except APIConnectionError as exc:
                raise _unreachable(settings.embed_base_url, exc) from None
        else:
            raise RuntimeError("Quota d'embeddings dépassé : configurer AI_ENDPOINTS_API_KEY")
    v = np.asarray(out, dtype=np.float32)
    return v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-12)


def embed_one(text: str) -> np.ndarray:
    return embed([text])[0]


def to_bytes(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype="<f4").tobytes()


def _reasoning(delta) -> str:
    """Les modèles de raisonnement (gpt-oss) envoient leur réflexion dans un champ non standard."""
    extra = getattr(delta, "model_extra", None) or {}
    return getattr(delta, "reasoning", None) or extra.get("reasoning") or extra.get("reasoning_content") or ""


def stream(model: str, messages: list[dict], max_tokens: int) -> Iterator[tuple[str, str | dict]]:
    """Produit ("reasoning", texte), ("content", texte), puis ("stats", {...})."""
    from openai import BadRequestError, UnprocessableEntityError

    t0 = time.perf_counter()
    first = None
    usage: dict = {}
    n_content = n_reason = 0
    kw = dict(model=model, messages=messages, stream=True, max_tokens=max_tokens, temperature=0.2)
    try:
        resp = _chat_client().chat.completions.create(**kw, stream_options={"include_usage": True})
    except (BadRequestError, UnprocessableEntityError):
        resp = _chat_client().chat.completions.create(**kw)
    for ev in resp:
        if getattr(ev, "usage", None):
            usage = ev.usage.model_dump()
        if not ev.choices:
            continue
        d = ev.choices[0].delta
        r = _reasoning(d)
        if r:
            n_reason += 1
            yield "reasoning", r
        if d.content:
            if first is None:
                first = time.perf_counter()
            n_content += 1
            yield "content", d.content
    total = time.perf_counter() - t0
    yield "stats", {
        "model": model,
        "first_token_ms": round(((first or time.perf_counter()) - t0) * 1000),
        "total_ms": round(total * 1000),
        "prompt_tokens": usage.get("prompt_tokens") or 0,
        # estimation si le serveur ne renvoie pas l'usage : ~1 token par morceau reçu
        "completion_tokens": usage.get("completion_tokens") or (n_content + n_reason),
        "usage_reported": bool(usage),
    }
