"""Vérifications avant démo : Valkey, index, modèles (embedding + chat), latences.

Usage : python -m demo.check   (code retour 0 si tout est vert)
"""
from __future__ import annotations

import sys
import time

from . import kb, llm
from .config import settings
from .valkey_client import describe_target, get_client

OK, KO, WARN = "\033[32m✔\033[0m", "\033[31m✘\033[0m", "\033[33m!\033[0m"


def main() -> int:
    failed = False
    print(f"Cible : {settings.target}  ->  Valkey {describe_target()}")
    print(f"        modèles : {settings.embed_model} @ {settings.embed_base_url}")
    print(f"                  {settings.chat_model} @ {settings.chat_base_url}")
    if settings.chat_api_key == "anonymous" and "ovh.net" in settings.chat_base_url:
        print(f"{WARN} Pas de clé AI Endpoints : accès anonyme limité à 2 requêtes/minute, insuffisant pour la démo")
    client = get_client()
    try:
        client.ping()
        v = client.info("server")
        print(f"{OK} Valkey {v.get('valkey_version') or v.get('redis_version')}")
    except Exception as exc:  # noqa: BLE001
        print(f"{KO} Valkey injoignable : {exc}")
        return 1

    if not kb.index_exists(client):
        print(f"{KO} Index {settings.index_name} absent : lancer `make load`")
        return 1
    n = kb.num_docs(client)
    print(f"{OK if n else KO} Index {settings.index_name} : {n} chunks · plein texte {'oui' if kb.text_enabled(client) else 'non'}")
    failed |= n == 0
    meta = {k.decode(): v.decode() for k, v in (client.hgetall(f"{settings.index_name}:meta") or {}).items()}
    if meta.get("embed_model") and meta["embed_model"] != settings.embed_model:
        print(f"{KO} Index vectorisé avec {meta['embed_model']} mais requêtes avec {settings.embed_model} : relancer `make load`")
        failed = True

    try:
        t0 = time.perf_counter()
        vec = llm.embed_one("Comment créer un index vectoriel dans Valkey ?")
        ms = (time.perf_counter() - t0) * 1000
        ok = vec.shape[0] == settings.vector_dim
        print(f"{OK if ok else KO} Embedding {settings.embed_model} : {vec.shape[0]} dimensions en {ms:.0f} ms")
        failed |= not ok
        res = kb.run(client, kb.knn_args(llm.to_bytes(vec), 3))
        has_score = bool(res["results"]) and all("similarity" in r for r in res["results"])
        print(f"{OK if has_score else KO} Recherche KNN : {res['ms']} ms · meilleur résultat « {res['results'][0].get('title') if res['results'] else '-'} »"
              f" ({res['results'][0].get('similarity') if res['results'] else '-'})")
        failed |= not has_score
    except Exception as exc:  # noqa: BLE001
        print(f"{KO} Embedding / recherche : {exc}")
        failed = True

    try:
        text, info = llm.complete([{"role": "user", "content": "Réponds juste OK."}], max_tokens=10)
        print(f"{OK if text else KO} Génération {settings.chat_model} : « {text[:30]} » en {info['ms']} ms")
        failed |= not text
    except Exception as exc:  # noqa: BLE001
        print(f"{KO} Génération : {exc}")
        failed = True

    print("\nTout est prêt." if not failed else "\nDes points sont à corriger.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
