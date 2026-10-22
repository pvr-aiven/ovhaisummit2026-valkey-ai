"""Vérifications avant démo : Valkey, index, embedding, deux modèles, prix. Code retour 0 si tout est vert."""
from __future__ import annotations

import sys
import time

from . import cache, llm, prices, router, vectors
from .config import settings
from .valkey_client import describe_target, get_client

OK, KO, WARN = "\033[32m✔\033[0m", "\033[31m✘\033[0m", "\033[33m!\033[0m"


def main() -> int:
    failed = False
    print(f"Cible : {settings.target}  ->  Valkey {describe_target()}")
    print(f"        modèle simple   : {settings.simple_model} (prix de {settings.simple_price_model})")
    print(f"        modèle complexe : {settings.complex_model} (prix de {settings.complex_price_model})")
    client = get_client()
    try:
        client.ping()
        print(f"{OK} Valkey {client.info('server').get('valkey_version')}")
    except Exception as exc:  # noqa: BLE001
        print(f"{KO} Valkey injoignable : {exc}")
        return 1
    for name in (settings.cache_index, settings.route_index):
        ok = vectors.index_exists(client, name)
        print(f"{OK if ok else KO} Index {name}" + ("" if ok else " absent : lancer `make load`"))
        failed |= not ok
    if failed:
        return 1
    n = router.count(client)
    print(f"{OK if all(n.values()) else KO} Exemples de routage : {n}")
    print(f"{OK} Cache : {cache.size(client)} réponse(s)")
    table = prices.load()
    for m in (settings.simple_price_model, settings.complex_price_model):
        p = table.get(m)
        print(f"{OK if p else WARN} Prix {m} : " + (f"{p[0]} € / {p[1]} € par million de tokens (entrée / sortie)" if p else "inconnu (compteur à 0)"))
    try:
        v = llm.embed_one("Quelle est la différence entre Valkey et Redis ?")
        r = router.route(client, llm.to_bytes(v))
        print(f"{OK} Routage d'une question simple -> {r['label']} ({r['votes']})")
    except Exception as exc:  # noqa: BLE001
        print(f"{KO} Embedding / routage : {exc}")
        failed = True
    for label in ("simple", "complex"):
        model = router.model_for(label)
        try:
            t0 = time.perf_counter()
            parts = [p for k, p in llm.stream(model, [{"role": "user", "content": "Réponds juste : OK"}], 400) if k == "content"]
            print(f"{OK if parts else KO} {model} : « {''.join(parts).strip()[:20]} » en {(time.perf_counter() - t0) * 1000:.0f} ms")
            failed |= not parts
        except Exception as exc:  # noqa: BLE001
            print(f"{KO} {model} : {exc}")
            failed = True
    print("\nTout est prêt." if not failed else "\nDes points sont à corriger.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
