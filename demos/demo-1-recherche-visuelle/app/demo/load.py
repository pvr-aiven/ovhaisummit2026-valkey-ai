"""Charge le catalogue dans Valkey : embeddings CLIP, HSET product:<id>, puis FT.CREATE.

L'index est créé APRÈS les HSET pour illustrer le message du talk : Valkey Search
indexe la donnée déjà présente (backfill) puis suit automatiquement chaque nouvel HSET.

Usage :
  python -m demo.load              # charge + crée l'index s'il n'existe pas
  python -m demo.load --reindex    # supprime puis recrée l'index (données conservées)
  python -m demo.load --no-index   # charge les hashes sans index (pour faire FT.CREATE en live)
  python -m demo.load --flush      # supprime d'abord toutes les clés product:*
"""
from __future__ import annotations

import argparse
import csv
import time

import numpy as np
from PIL import Image

from . import catalog
from .config import settings
from .embeddings import embed_images, to_bytes
from .valkey_client import describe_target, get_client


def read_catalog() -> list[dict]:
    if not settings.catalog_csv.exists():
        raise SystemExit(f"{settings.catalog_csv} introuvable : lancez d'abord `make dataset`.")
    with open(settings.catalog_csv, newline="", encoding="utf-8") as fh:
        rows, seen = [], set()
        for r in csv.DictReader(fh):
            if r["id"] not in seen:  # un id en double écraserait un hash et fausserait le décompte
                seen.add(r["id"])
                rows.append(r)
        return rows


def compute_embeddings(rows: list[dict], batch: int = 64) -> np.ndarray:
    ids_file = settings.embeddings_file.with_suffix(".ids")
    ids = [settings.image_model] + [r["id"] for r in rows]  # le cache dépend aussi du modèle
    if settings.embeddings_file.exists() and ids_file.exists() and ids_file.read_text().split("\n") == ids:
        print("Embeddings déjà calculés : réutilisation du cache.")
        return np.load(settings.embeddings_file)
    print(f"Calcul des embeddings CLIP pour {len(rows)} images (CPU, quelques minutes la première fois)…")
    out, t0 = [], time.time()
    for i in range(0, len(rows), batch):
        imgs = [Image.open(settings.images_dir / r["image"]) for r in rows[i:i + batch]]
        out.append(embed_images(imgs, batch_size=batch))
        print(f"  {min(i + batch, len(rows))}/{len(rows)}  ({time.time() - t0:.0f}s)", end="\r")
    print()
    vecs = np.vstack(out).astype(np.float32)
    np.save(settings.embeddings_file, vecs)
    ids_file.write_text("\n".join(ids))
    return vecs


def flush_products(client) -> int:
    n = 0
    for key in client.scan_iter(match=f"{settings.key_prefix}*", count=1000):
        client.delete(key)
        n += 1
    return n


def load_hashes(client, rows: list[dict], vecs: np.ndarray, batch: int = 500) -> None:
    t0 = time.time()
    pipe = client.pipeline(transaction=False)
    for i, (r, v) in enumerate(zip(rows, vecs), 1):
        pipe.hset(f"{settings.key_prefix}{r['id']}", mapping={
            "id": r["id"],
            "name": r["name"],
            "gender": catalog.slug(r["gender"]),
            "category": catalog.slug(r["category"]),
            "color": catalog.slug(r["color"]),
            "price": r["price"],
            "stock": r["stock"],
            "image": r["image"],
            catalog.VECTOR_FIELD: to_bytes(v),
        })
        if i % batch == 0:
            pipe.execute()
    pipe.execute()
    print(f"{len(rows)} hashes écrits en {time.time() - t0:.1f}s")


def wait_indexed(client, expected: int, timeout: float = 300) -> None:
    t0, last, still = time.time(), -1, 0
    while time.time() - t0 < timeout:
        info = catalog.index_info(client)
        n = int(float(info.get("num_docs", 0) or 0))
        state = str(info.get("state", "") or "")
        print(f"  backfill : {n}/{expected} documents indexés {state}", end="\r")
        if n >= expected:
            print(f"\nIndex prêt en {time.time() - t0:.1f}s")
            return
        still = still + 1 if n == last else 0
        last = n
        if state == "ready" and still >= 6:  # backfill terminé mais certains hashes non indexés
            print(f"\n! Index prêt avec {n}/{expected} documents. "
                  f"Échecs d'indexation : {info.get('hash_indexing_failures', '?')} (vecteur de mauvaise taille ?)")
            return
        time.sleep(0.5)
    print("\n! Backfill non terminé dans le délai : vérifier FT.INFO")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reindex", action="store_true")
    ap.add_argument("--no-index", action="store_true")
    ap.add_argument("--flush", action="store_true")
    args = ap.parse_args()

    client = get_client()
    client.ping()
    print(f"Cible : {settings.target}  ->  {describe_target()}")

    rows = read_catalog()
    vecs = compute_embeddings(rows)
    if vecs.shape[1] != settings.vector_dim:
        raise SystemExit(f"Dimension {vecs.shape[1]} != VECTOR_DIM={settings.vector_dim}")

    if args.flush:
        print(f"{flush_products(client)} clés supprimées")
    load_hashes(client, rows, vecs)

    if args.no_index:
        print("Index non créé (--no-index). Commande à lancer en live :")
        print("  " + catalog.display_command(catalog.create_index_args()))
        return
    cmd, with_text = catalog.create_index(client, drop_existing=args.reindex)
    if cmd:
        print("Index créé :\n  " + catalog.display_command(cmd))
        if not with_text:
            print("  (champ TEXT non supporté par ce serveur : recherche plein texte désactivée)")
    else:
        print(f"Index {settings.index_name} déjà présent (utiliser --reindex pour le recréer)")
    wait_indexed(client, len(rows))


if __name__ == "__main__":
    main()
