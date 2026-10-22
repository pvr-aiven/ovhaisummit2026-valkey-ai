"""Prépare Valkey : index du cache sémantique, index du routeur et exemples de routage.

Usage :
  python -m demo.load            # crée les index, vectorise et charge les exemples de routes.yaml
  python -m demo.load --reset    # supprime aussi le cache, les compteurs et les exemples appris en direct
"""
from __future__ import annotations

import argparse

from . import cache, llm, prices, router, stats, vectors
from .config import settings
from .valkey_client import describe_target, get_client


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()

    import yaml

    client = get_client()
    client.ping()
    print(f"Cible : {settings.target}  ->  {describe_target()}")
    if args.reset:
        print(f"{cache.clear(client)} entrées de cache supprimées")
        stats.reset(client)
        for k in client.scan_iter(match=f"{settings.route_prefix}*", count=500):
            client.delete(k)
        vectors.drop_index(client, settings.route_index)

    for name, cmd in (("cache", cache.ensure_index(client)), ("routeur", router.ensure_index(client))):
        print(f"Index {name} : " + ("créé\n  " + vectors.display(cmd) if cmd else "déjà présent"))

    examples = yaml.safe_load(open(settings.routes_file, encoding="utf-8"))
    pairs = [(t, lab) for lab, key in (("simple", "simple"), ("complex", "complex")) for t in examples.get(key, [])]
    vecs = llm.embed([t for t, _ in pairs])
    for (text, label), v in zip(pairs, vecs):
        router.add_example(client, text, label, llm.to_bytes(v))
    print(f"{len(pairs)} exemples de routage chargés ({sum(1 for _, l in pairs if l == 'simple')} simples, "
          f"{sum(1 for _, l in pairs if l == 'complex')} complexes) avec {settings.embed_model}")
    try:
        p = prices.refresh()
        print(f"Prix AI Endpoints mis à jour ({len(p)} modèles) -> {settings.prices_file}")
    except Exception as exc:  # noqa: BLE001
        print(f"! Prix non mis à jour ({exc}) : valeurs par défaut du 12/10/2026")


if __name__ == "__main__":
    main()
