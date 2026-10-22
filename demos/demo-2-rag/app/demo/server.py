"""API + interface web de la démo 2 (assistant RAG)."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import history, kb, rag
from .config import settings
from .valkey_client import describe_target, get_client

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="Démo 2 – Assistant RAG avec Valkey et AI Endpoints")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class AskIn(BaseModel):
    session: str
    question: str = Field(min_length=1, max_length=2000)
    sources: list[str] = Field(default_factory=list)
    use_rag: bool = True
    compare_fulltext: bool = False


def _count(client, source: str) -> int:
    raw = client.execute_command("FT.SEARCH", settings.index_name, f"@source:{{{kb.tag(source)}}}",
                                 "NOCONTENT", "LIMIT", "0", "1", "DIALECT", "2")
    return int(raw[0]) if raw else 0


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/meta")
def meta() -> dict:
    client = get_client()
    ready = kb.index_exists(client)
    meta_raw = client.hgetall(f"{settings.index_name}:meta") or {}
    kbmeta = {k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v
              for k, v in meta_raw.items()}
    return {
        "target": settings.target,
        "valkey": describe_target(),
        "index": settings.index_name,
        "ready": ready,
        "num_docs": kb.num_docs(client) if ready else 0,
        "sources": [{"tag": t, "label": label, "count": _count(client, t) if ready else 0}
                    for t, label in kb.SOURCES.items()],
        "text_search": kb.text_enabled(client) if ready else False,
        "embed_model": settings.embed_model,
        "chat_model": settings.chat_model,
        "llm_host": settings.chat_base_url.split("//")[-1].split("/")[0],
        "kb_meta": kbmeta,
        "embed_mismatch": bool(kbmeta) and kbmeta.get("embed_model") != settings.embed_model,
    }


@app.post("/api/ask")
def ask(q: AskIn) -> StreamingResponse:
    client = get_client()
    try:
        history.key(q.session)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    def events():
        try:
            for e in rag.ask(client, q.session, q.question, q.sources, q.use_rag, q.compare_fulltext):
                yield f"data: {json.dumps(e, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001  l'erreur est affichée dans l'interface
            yield f"data: {json.dumps({'type': 'error', 'message': f'{type(exc).__name__}: {exc}'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/history/{session}")
def get_history(session: str) -> dict:
    try:
        msgs, info = history.recent(get_client(), session, n=50)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"messages": msgs, **info}


@app.delete("/api/history/{session}")
def delete_history(session: str) -> dict:
    try:
        history.clear(get_client(), session)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "command": f"DEL {settings.history_prefix}{session}"}
