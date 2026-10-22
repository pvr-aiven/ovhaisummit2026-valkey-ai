"""Vectorise les chunks (BGE-M3) et les charge dans Valkey, puis crée l'index.

Usage :
  python -m demo.load            # embeddings (cache local) + HSET chunk:* + FT.CREATE
  python -m demo.load --reindex  # recrée l'index, données conservées
  python -m demo.load --flush    # supprime d'abord les chunks existants
"""
from __future__ import annotations

import argparse
import json
import re
import time

import numpy as np

from . import kb
from .config import settings
from .llm import embed, to_bytes
from .valkey_client import describe_target, get_client


def read_chunks() -> list[dict]:
    if not settings.chunks_file.exists():
        raise SystemExit(f"{settings.chunks_file} introuvable : lancer d'abord `make ingest`.")
    return [json.loads(line) for line in settings.chunks_file.read_text(encoding="utf-8").splitlines() if line]


def embedding_input(c: dict) -> str:
    """On vectorise le texte précédé du titre et de la section : le chunk garde son contexte."""
    head = c["title"] + (f" › {c['section']}" if c["section"] and c["section"] != c["title"] else "")
    return f"{head}\n\n{c['text']}"


def cache_path() -> tuple:
    slug = re.sub(r"[^a-z0-9]+", "-", f"{settings.embed_model}-{settings.embed_base_url}".lower()).strip("-")[:80]
    base = settings.data_dir / f"embeddings-{slug}"
    return base.with_suffix(".npy"), base.with_suffix(".ids")


def compute_embeddings(chunks: list[dict]) -> np.ndarray:
    npy, ids_file = cache_path()
    ids = [c["id"] for c in chunks]
    if npy.exists() and ids_file.exists() and ids_file.read_text().split("\n") == ids:
        print(f"Embeddings déjà calculés pour {settings.embed_model} : réutilisation du cache.")
        return np.load(npy)
    print(f"Vectorisation de {len(chunks)} chunks avec {settings.embed_model} ({settings.embed_base_url})…")
    t0 = time.time()
    vecs = []
    step = settings.embed_batch
    for i in range(0, len(chunks), step):
        vecs.append(embed([embedding_input(c) for c in chunks[i:i + step]]))
        print(f"  {min(i + step, len(chunks))}/{len(chunks)}  ({time.time() - t0:.0f}s)", end="\r")
    print()
    out = np.vstack(vecs).astype(np.float32)
    np.save(npy, out)
    ids_file.write_text("\n".join(ids))
    return out


def flush(client) -> int:
    n = 0
    for key in client.scan_iter(match=f"{settings.key_prefix}*", count=1000):
        client.delete(key)
        n += 1
    return n


def load(client, chunks: list[dict], vecs: np.ndarray) -> None:
    t0 = time.time()
    pipe = client.pipeline(transaction=False)
    for i, (c, v) in enumerate(zip(chunks, vecs), 1):
        pipe.hset(f"{settings.key_prefix}{c['id']}", mapping={
            "doc_id": kb.tag(c["doc_id"]), "url": c["url"], "source": kb.tag(c["source"]), "type": kb.tag(c["type"]),
            "title": c["title"], "section": c["section"], "text": c["text"], "position": c["position"],
            kb.VECTOR_FIELD: to_bytes(v),
        })
        if i % 200 == 0:
            pipe.execute()
    pipe.execute()
    client.hset(f"{settings.index_name}:meta", mapping={"embed_model": settings.embed_model, "embed_base_url": settings.embed_base_url,
                                    "dim": vecs.shape[1], "chunks": len(chunks), "loaded_at": int(time.time())})
    print(f"{len(chunks)} chunks écrits en {time.time() - t0:.1f}s")


def wait_indexed(client, expected: int, timeout: float = 300) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        n = kb.num_docs(client)
        print(f"  backfill : {n}/{expected}", end="\r")
        if n >= expected:
            print(f"\nIndex prêt en {time.time() - t0:.1f}s")
            return
        time.sleep(0.5)
    print("\n! Backfill non terminé : vérifier FT.INFO")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reindex", action="store_true")
    ap.add_argument("--flush", action="store_true")
    args = ap.parse_args()

    client = get_client()
    client.ping()
    print(f"Cible : {settings.target}  ->  {describe_target()}")
    chunks = read_chunks()
    vecs = compute_embeddings(chunks)
    if vecs.shape[1] != settings.vector_dim:
        raise SystemExit(f"Dimension {vecs.shape[1]} != VECTOR_DIM={settings.vector_dim}")
    if args.flush:
        print(f"{flush(client)} clés supprimées")
    load(client, chunks, vecs)
    cmd, with_text = kb.create_index(client, drop_existing=args.reindex)
    print(("Index créé :\n  " + kb.display_command(cmd)) if cmd else f"Index {settings.index_name} déjà présent")
    if not with_text:
        print("  (recherche plein texte indisponible sur ce serveur)")
    wait_indexed(client, len(chunks))


if __name__ == "__main__":
    main()
