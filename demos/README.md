# Démos – « Valkey & IA : votre cache sait déjà chercher » (OVHcloud AI Summit 2026)

Chaque démo est autonome : son propre dossier, son `README.md` (mode opératoire) et un `Makefile`.
Toutes se lancent avec Docker, **les mêmes commandes et la même variable de cible** :

```bash
make <commande> TARGET=local           # Valkey 9.1 dans Docker (+ AI Endpoints pour les démos 2 et 3) : défaut
make <commande> TARGET=local-offline   # Valkey 9.1 dans Docker, sans Internet (Ollama pour les démos 2 et 3)
make <commande> TARGET=ovhcloud        # OVHcloud Managed Valkey 9.1 (+ AI Endpoints)
make <commande> TARGET=aiven           # Aiven for Valkey (+ AI Gateway)
```

`TARGET=ovh` reste accepté (alias de `ovhcloud`). Chaque cible lit `env/<cible>.env` : copier `env/<cible>.env.example` pour `ovhcloud` et `aiven`.

| Commande | Rôle (identique dans chaque démo) |
|---|---|
| `make help` | liste des commandes et cible courante |
| `make prepare` | tout préparer la veille : build, données, index, vérifications |
| `make up` / `make down` | lancer / arrêter l'interface (les données Valkey locales sont conservées) |
| `make reset` | avant de monter sur scène : remettre la démo à zéro |
| `make check` | vérifier Valkey, index, modèles et latences |
| `make load` / `make reindex` | (re)charger les données / recréer l'index |
| `make cli` | valkey-cli sur la cible courante |
| `make logs` / `make test` | journaux / tests unitaires |
| `make ollama` | télécharger les modèles de `local-offline` (démos 2 et 3) |

Commandes propres à une démo : `dataset`, `warmup` (démo 1), `ingest`, `ingest-offline` (démo 2), `prices` (démo 3).

| Démo | Dossier | État |
|---|---|---|
| 1 · Recherche visuelle et hybride | [`demo-1-recherche-visuelle/`](demo-1-recherche-visuelle/README.md) | prête à tester |
| 2 · Assistant RAG de bout en bout | [`demo-2-rag/`](demo-2-rag/README.md) | prête à tester (http://localhost:8001) |
| 3 · Cache et routage sémantiques | [`demo-3-cache-routage/`](demo-3-cache-routage/README.md) | prête à tester (http://localhost:8002) |

Prérequis communs : Docker avec Compose ≥ 2.24, `make`, ~6 Go de disque.
