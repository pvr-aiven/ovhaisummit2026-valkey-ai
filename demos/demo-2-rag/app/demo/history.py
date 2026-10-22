"""Historique de conversation dans un stream Valkey : chat:<session>.

XADD ajoute un message, XREVRANGE relit les derniers, EXPIRE fait disparaître
une conversation inactive. Rien à nettoyer à la main.
"""
from __future__ import annotations

import json
import re
import time

from .config import settings
from .kb import display_command

_SID = re.compile(r"^[A-Za-z0-9_-]{4,64}$")


def key(session: str) -> str:
    if not _SID.match(session or ""):
        raise ValueError("identifiant de session invalide")
    return f"{settings.history_prefix}{session}"


def _d(v):
    return v.decode() if isinstance(v, (bytes, bytearray)) else v


def recent(client, session: str, n: int | None = None) -> tuple[list[dict], dict]:
    """Derniers messages, du plus ancien au plus récent."""
    n = n or settings.history_turns
    args = ["XREVRANGE", key(session), "+", "-", "COUNT", str(n)]
    t0 = time.perf_counter()
    raw = client.execute_command(*args) or []
    ms = (time.perf_counter() - t0) * 1000
    msgs = []
    for entry_id, fields in reversed(raw):
        f = {_d(fields[i]): _d(fields[i + 1]) for i in range(0, len(fields), 2)} if isinstance(fields, list) \
            else {_d(k): _d(v) for k, v in fields.items()}
        msgs.append({"id": _d(entry_id), "role": f.get("role"), "content": f.get("content", ""),
                     "sources": json.loads(f.get("sources") or "[]")})
    return msgs, {"command": display_command(args), "ms": round(ms, 2), "count": len(msgs)}


def append(client, session: str, role: str, content: str, sources: list | None = None) -> dict:
    k = key(session)
    args = ["XADD", k, "*", "role", role, "content", content]
    if sources:
        args += ["sources", json.dumps(sources, ensure_ascii=False)]
    t0 = time.perf_counter()
    client.execute_command(*args)
    client.execute_command("EXPIRE", k, str(settings.history_ttl))
    ms = (time.perf_counter() - t0) * 1000
    short = args[:7] + (["sources", "[…]"] if sources else [])
    short[6] = (content[:60] + "…") if len(content) > 60 else content
    return {"command": display_command(short) + f"   ·   EXPIRE {k} {settings.history_ttl}", "ms": round(ms, 2)}


def length(client, session: str) -> int:
    return int(client.execute_command("XLEN", key(session)) or 0)


def clear(client, session: str) -> None:
    client.delete(key(session))


def clear_all(client) -> int:
    n = 0
    for k in client.scan_iter(match=f"{settings.history_prefix}*", count=500):
        client.delete(k)
        n += 1
    return n


if __name__ == "__main__":  # python -m demo.history : vide toutes les conversations
    from .valkey_client import get_client

    print(f"{clear_all(get_client())} conversation(s) supprimée(s)")
