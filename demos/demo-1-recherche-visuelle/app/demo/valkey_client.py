"""Connexion Valkey (local sans TLS, OVHcloud / Aiven en TLS)."""
from __future__ import annotations

from functools import lru_cache

import valkey

from .config import settings

_SCHEMES = {"valkey://": "redis://", "valkeys://": "rediss://"}


def normalize_url(url: str) -> str:
    """valkey:// et valkeys:// sont acceptés et convertis vers les schémas historiques compris par tous les clients."""
    for src, dst in _SCHEMES.items():
        if url.startswith(src):
            return dst + url[len(src):]
    return url


@lru_cache(maxsize=1)
def get_client() -> valkey.Valkey:
    url = normalize_url(settings.valkey_url)
    kwargs: dict = {"decode_responses": False, "socket_timeout": 10, "health_check_interval": 30}
    if url.startswith("rediss://"):
        kwargs["ssl_cert_reqs"] = "required"
        if settings.valkey_ca_cert:
            kwargs["ssl_ca_certs"] = settings.valkey_ca_cert
    return valkey.from_url(url, **kwargs)


def describe_target() -> str:
    """URL affichable sans mot de passe."""
    url = normalize_url(settings.valkey_url)
    if "@" in url:
        scheme, rest = url.split("://", 1)
        url = f"{scheme}://***@{rest.split('@', 1)[1]}"
    return url
