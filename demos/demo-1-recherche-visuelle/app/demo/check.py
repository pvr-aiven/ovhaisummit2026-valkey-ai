"""Vérifications avant démo : connexion, version, module Search, index, latence.

Usage : python -m demo.check
Code retour 0 si tout est vert, 1 sinon.
"""
from __future__ import annotations

import statistics
import sys
import time

from . import catalog
from .config import settings
from .valkey_client import describe_target, get_client

OK, KO, WARN = "\033[32m✔\033[0m", "\033[31m✘\033[0m", "\033[33m!\033[0m"


def main() -> int:
    failed = False
    print(f"Cible : {settings.target}  ->  {describe_target()}")
    client = get_client()

    try:
        client.ping()
        print(f"{OK} Connexion Valkey")
    except Exception as exc:  # noqa: BLE001
        print(f"{KO} Connexion impossible : {exc}")
        print("   Vérifier VALKEY_URL, l'IP autorisée (OVH : « IPs autorisées ») et le TLS (rediss://).")
        return 1

    info = client.info("server")
    version = info.get("valkey_version") or info.get("redis_version")
    print(f"{OK if str(version).startswith('9') else WARN} Version serveur : {version}")

    try:
        mods = client.execute_command("MODULE", "LIST") or []
        names = []
        for m in mods:  # valkey-py renvoie une liste de dicts à clés bytes
            d = m if isinstance(m, dict) else catalog._pairs_to_dict(m)
            raw = d.get(b"name", d.get("name"))
            names.append(raw.decode() if isinstance(raw, bytes) else str(raw))
        has_search = any("search" in n.lower() for n in names)
        print(f"{OK if has_search else KO} Modules chargés : {', '.join(names) or 'aucun'}")
        failed |= not has_search
    except Exception:  # noqa: BLE001  (MODULE LIST peut être interdit sur un service managé)
        try:
            client.execute_command("FT._LIST")
            print(f"{OK} Module Search disponible (FT._LIST répond)")
        except Exception as exc:  # noqa: BLE001
            print(f"{KO} Module Search indisponible : {exc}")
            return 1

    if not catalog.index_exists(client):
        print(f"{WARN} Index {settings.index_name} absent : lancer `make load`")
        return 1
    info = catalog.index_info(client)
    n = int(float(info.get("num_docs", 0) or 0))
    print(f"{OK if n else KO} Index {settings.index_name} : {n} documents")
    failed |= n == 0

    # Latence : 20 recherches KNN à partir d'un produit existant
    key = next(client.scan_iter(match=f"{settings.key_prefix}*", count=100), None)
    if key:
        vec = catalog.get_vector(client, key)
        f = catalog.Filters(in_stock=True)
        _, docs = catalog.parse_search_reply(client.execute_command(*catalog.knn_search_args(f, vec, 3)))
        has_score = bool(docs) and all("similarity" in d for d in docs)
        print(f"{OK if has_score else KO} Score de similarité renvoyé par FT.SEARCH")
        if not has_score and docs:
            print(f"   champs reçus : {sorted(k for k in docs[0] if k != 'key')}")
        failed |= not has_score
        lat = []
        for _ in range(20):
            t0 = time.perf_counter()
            client.execute_command(*catalog.knn_search_args(f, vec, 12))
            lat.append((time.perf_counter() - t0) * 1000)
        print(f"{OK} Recherche hybride KNN : médiane {statistics.median(lat):.1f} ms, "
              f"max {max(lat):.1f} ms (aller-retour réseau inclus)")

    print("\nTout est prêt." if not failed else "\nDes points sont à corriger.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
