"""Prépare le catalogue de chaussures : images + catalog.csv dans DATA_DIR.

Deux sources possibles :
  --source hf   (défaut) jeu public « Fashion Product Images (Small) » sur Hugging Face,
                filtré sur les chaussures. Prix et stock sont générés de façon déterministe.
  --source csv  votre propre catalogue : un CSV (id,name,gender,category,color,image[,price,stock])
                et un dossier d'images. Utile pour des visuels haute définition sur scène.

Usage :
  python -m demo.prepare_dataset                    # HF, MAX_PRODUCTS chaussures
  python -m demo.prepare_dataset --source csv --csv mon_catalogue.csv --images-dir mes_images/
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import shutil
from pathlib import Path

from .config import settings

HF_DATASET = "ashraq/fashion-product-images-small"

# Fourchettes de prix (EUR) par type d'article, pour un catalogue crédible
PRICE_RANGES = {
    "sports shoes": (49, 179), "casual shoes": (39, 139), "formal shoes": (59, 199),
    "heels": (29, 149), "flats": (19, 89), "sandals": (19, 99), "sports sandals": (24, 89),
    "flip flops": (9, 39), "booties": (49, 169),
}
DEFAULT_RANGE = (19, 129)
FIELDS = ["id", "name", "gender", "category", "color", "price", "stock", "image"]


def _h(value: str, salt: str) -> int:
    return int(hashlib.sha256(f"{salt}:{value}".encode()).hexdigest(), 16)


def synth_price(pid: str, category: str) -> float:
    lo, hi = PRICE_RANGES.get(category.lower(), DEFAULT_RANGE)
    return float(lo + _h(pid, "price") % (hi - lo)) + 0.99  # prix en x,99


def synth_stock(pid: str) -> int:
    # ~20 % de produits en rupture, sinon 1 à 40 en stock
    return 0 if _h(pid, "stock") % 5 == 0 else 1 + _h(pid, "qty") % 40


def from_hf(limit: int) -> list[dict]:
    from datasets import load_dataset

    ds = load_dataset(HF_DATASET, split="train")
    # filtre sur une seule colonne : évite de décoder les 44 000 images
    ds = ds.filter(lambda m: m == "Footwear", input_columns=["masterCategory"])
    ds = ds.shuffle(seed=42)  # échantillon varié (tous types de chaussures), reproductible
    settings.images_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for r in ds:
        if len(rows) >= limit:
            break
        if r["image"] is None:
            continue
        pid = str(r["id"])
        category = r["articleType"] or "Shoes"
        img_name = f"{pid}.jpg"
        r["image"].convert("RGB").save(settings.images_dir / img_name, quality=92)
        rows.append({
            "id": pid,
            "name": r["productDisplayName"] or category,
            "gender": r["gender"] or "Unisex",
            "category": category,
            "color": r["baseColour"] or "unknown",
            "price": synth_price(pid, category),
            "stock": synth_stock(pid),
            "image": img_name,
        })
    return rows


def from_csv(csv_path: Path, images_dir: Path, limit: int) -> list[dict]:
    settings.images_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if len(rows) >= limit:
                break
            pid = str(r["id"])
            src = images_dir / r["image"]
            if not src.exists():
                print(f"  ! image introuvable, produit ignoré : {src}")
                continue
            dst_name = f"{pid}{src.suffix.lower()}"
            shutil.copyfile(src, settings.images_dir / dst_name)
            category = r.get("category") or "Shoes"
            rows.append({
                "id": pid,
                "name": r.get("name") or category,
                "gender": r.get("gender") or "Unisex",
                "category": category,
                "color": r.get("color") or "unknown",
                "price": float(r["price"]) if r.get("price") else synth_price(pid, category),
                "stock": int(r["stock"]) if r.get("stock") else synth_stock(pid),
                "image": dst_name,
            })
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=["hf", "csv"], default="hf")
    ap.add_argument("--csv", type=Path, help="CSV du catalogue (source csv)")
    ap.add_argument("--images-dir", type=Path, help="Dossier des images (source csv)")
    ap.add_argument("--limit", type=int, default=settings.max_products)
    args = ap.parse_args()

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    if args.source == "hf":
        print(f"Téléchargement de {HF_DATASET} (chaussures uniquement, {args.limit} max)…")
        rows = from_hf(args.limit)
    else:
        if not args.csv or not args.images_dir:
            ap.error("--source csv nécessite --csv et --images-dir")
        rows = from_csv(args.csv, args.images_dir, args.limit)

    with open(settings.catalog_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    if settings.embeddings_file.exists():
        settings.embeddings_file.unlink()  # le catalogue a changé : embeddings à recalculer
    print(f"OK : {len(rows)} produits -> {settings.catalog_csv}")


if __name__ == "__main__":
    main()
