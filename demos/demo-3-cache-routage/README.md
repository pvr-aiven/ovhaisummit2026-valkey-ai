# Démo 3 – Cache et routage sémantiques

**Slide :** « Démo 3 : cache et routage sémantiques » · **Durée sur scène :** 6 min · **Cibles :** `local` (Valkey Docker + AI Endpoints), `local-offline` (Valkey Docker + Ollama, sans Internet), `ovhcloud` (Managed Valkey + AI Endpoints), `aiven` (Aiven for Valkey, AI Gateway à venir)

## Ce que la démo montre

1. **Première question** : appel au modèle, latence en secondes, tokens et coût affichés.
2. **Reformulation de la même question** : réponse servie par le **cache sémantique** dans Valkey (`FT.SEARCH … KNN 1`, similarité ≥ 0,90), en quelques millisecondes, 0 token, 0 €.
3. **Cas limite** : une question *voisine* mais différente (« … et Memcached ? », similarité ~0,71) n'est **pas** servie par le cache.
4. **Routage sémantique** : une question simple part vers **Mistral Small 3.2**, une question complexe vers **gpt-oss-120b** (modèle de raisonnement, dont la « réflexion » s'affiche en direct).
5. **Compteurs en direct** (hash Valkey `stats:demo3`) : tokens et euros économisés, taux de cache, latence modèle / cache, projection sur 1 million de questions.

Bonus : sous chaque réponse, « c'était simple / complexe » ajoute la question comme nouvel exemple du routeur (`HSET route:…`), sans réentraînement.

## Architecture

```
 Navigateur ──► app (FastAPI, Docker sur le portable)
                 ├─ 1. GET exact:<sha>                         cache exact (question normalisée)
                 ├─ 2. bge-m3 → vecteur (un seul, réutilisé)
                 ├─ 3. FT.SEARCH idx:cache  KNN 1              cache sémantique (seuil 0,90)
                 ├─ 4. FT.SEARCH idx:route  KNN 5              routeur : vote des 5 exemples les plus proches
                 ├─ 5. Mistral Small 3.2  ou  gpt-oss-120b     API compatible OpenAI (AI Endpoints / Ollama / AI Gateway)
                 ├─ 6. HSET cache:<id> + EXPIRE, SET exact:<sha>
                 └─ 7. HINCRBY / HINCRBYFLOAT stats:demo3      compteurs
```

## Onglet « Comment ça marche »

http://localhost:8002/comment-ca-marche rejoue la **cascade** pour la dernière question posée (ou n'importe quelle question saisie), avec les vraies valeurs, **sans appeler le modèle de génération** :

1. cache exact (question normalisée → empreinte → `GET`) · 2. vecteur BGE-M3 · 3. cache sémantique (3 questions en cache les plus proches, jauge du seuil) · 4. routage (5 exemples voisins, leur étiquette, le vote, le seuil de prudence) · 5. modèle choisi et ses prix · 6. mise en cache. · 7. **en production** (hors du chemin de la réponse) : schéma de la boucle d'évaluation continue avec Langfuse auto-hébergé (traces, évaluateur LLM-as-a-Judge sur 2 % des réponses du petit modèle, Experiments sur un jeu de référence), un petit job qui renvoie les réponses jugées insuffisantes comme exemples « complexe » du routeur dans Valkey, et un exemple de code simplifié.

Une bulle descend la cascade à chaque appui sur → (télécommande compatible) et s'arrête à l'étape qui répond. Deux curseurs permettent de **changer les seuils en direct** : à 0,70, la question « … et Memcached ? » serait servie par le cache avec la réponse sur Redis, ce qui montre pourquoi le seuil est à 0,90. Par défaut, la question analysée ignore sa propre réponse en cache (pour rejouer son premier passage) ; une case permet de voir l'état actuel.

## Comment sont calculées les économies

- **Coût réel** : tokens réellement consommés × prix du modèle utilisé (0 € pour une réponse du cache).
- **Coût de référence** : la même question envoyée au **grand modèle, sans cache**, avec le même nombre de tokens.
- **Économie** = référence − réel. Estimation prudente : un modèle de raisonnement comme gpt-oss-120b produirait en réalité plus de tokens que le petit modèle.
- **Prix** : relus sur la [page des prix OVHcloud](https://www.ovhcloud.com/fr/public-cloud/prices/#ai-endpoints) à chaque `make load` (`make prices` pour les seuls prix), en € HT. Au 12/10/2026 : Mistral Small 3.2 = 0,09 € / 0,28 € par million de tokens (entrée / sortie), gpt-oss-120b = 0,08 € / 0,40 €.

> **À savoir pour le discours** : sur AI Endpoints, l'écart de prix entre ces deux modèles est faible (×1,4 en sortie). Le gain du routage vient surtout de la **latence** (le grand modèle réfléchit plusieurs secondes, même pour « 17 × 23 ») et du **volume de tokens** de la réflexion. Le gros gain financier vient du **cache**. Pour un écart de prix plus spectaculaire, mettre `COMPLEX_MODEL=Qwen3.5-397B-A17B` (3,60 €/M en sortie, ×13). La slide « 500x » reprend des prix Bedrock : la réadapter aux prix AI Endpoints.

## Prérequis

- Docker avec **Compose ≥ 2.24**, `make`
- Une **clé AI Endpoints** dans `env/secrets.env` (copier `secrets.env.example`)
- Plan B hors ligne : [Ollama](https://ollama.com) puis `make ollama` (bge-m3, mistral, gpt-oss:20b, ~18 Go)

## Mode opératoire

### A. Cible locale (Valkey Docker + AI Endpoints) : par défaut

```bash
cd demos/demo-3-cache-routage
cp env/secrets.env.example env/secrets.env      # coller la clé AI Endpoints
make prepare      # build + index + exemples de routage + prix du jour + vérifications
make up           # → http://localhost:8002
```

### B. Plan B sans Internet (Ollama)

```bash
make ollama
make prepare TARGET=local-offline     # index séparés (idx:cache_offline, idx:route_offline)
make up TARGET=local-offline
```

Le compteur chiffre les appels « comme sur AI Endpoints » (`SIMPLE_PRICE_MODEL`, `COMPLEX_PRICE_MODEL`). gpt-oss:20b sur un portable est lent : c'est l'occasion de dire que le routage évite justement le grand modèle quand il n'est pas utile.

### C. OVHcloud (Managed Valkey 9.1 + AI Endpoints)

```bash
cp env/ovhcloud.env.example env/ovhcloud.env     # VALKEY_URL rediss://…
make prepare TARGET=ovhcloud && make up TARGET=ovhcloud
```

### D. Aiven (prête, à valider)

```bash
cp env/aiven.env.example env/aiven.env   # Service URI + CA dans ./certs/aiven-ca.pem
make prepare TARGET=aiven && make up TARGET=aiven
```

Quand l'AI Gateway sera disponible : renseigner `CHAT_BASE_URL`, `CHAT_API_KEY` et les noms de modèles, puis `make reset TARGET=aiven` (si le modèle d'embedding change, les exemples du routeur doivent être revectorisés : `reset` le fait).

## Déroulé sur scène (6 min)

| Temps | Action | Ce qu'on dit |
|---|---|---|
| 0:00 | Interface ouverte, compteurs à zéro (`make reset`) | « Deux leviers pour la facture : ne pas rappeler le modèle, et appeler le bon. » |
| 0:30 | **1 · Première question** : « Quelle est la différence entre Valkey et Redis ? » | Panneau : cache exact absent, cache sémantique vide, routage *simple*, Mistral Small, ~1 à 3 s. Puis `HSET cache:…` + `EXPIRE`. |
| 1:30 | **2 · Reformulation** : « En quoi Valkey se distingue-t-il de Redis ? » | Similarité ~0,96 ≥ 0,90 : **réponse servie par Valkey, 0 token, 0 €**. Mesuré : ~0,2 s au total contre ~7 s, dont ~1 ms dans Valkey et le reste pour vectoriser la question (appel BGE-M3). Le cache exact (même question retapée) répond, lui, en quelques ms. |
| 2:15 | **3 · Cas limite** : « … et Memcached ? » | ~0,71 : sous le seuil, appel au modèle. « Le seuil évite de servir une mauvaise réponse. » |
| 3:00 | **5 · Complexe** : la stratégie de cache pour 2 millions de questions | Routage *complexe* (vote des voisins), gpt-oss-120b : la réflexion défile, plusieurs secondes, beaucoup plus de tokens. |
| 4:15 | **4 · Simple** : « Comment supprimer une clé dans Valkey ? » | Petit modèle, moins d'une seconde. « Inutile de sortir le grand modèle pour ça. » |
| 5:00 | Compteurs | € et tokens économisés, taux de cache, latence modèle / cache, **projection sur 1 million de questions**. |
| 5:30 | *(Option)* « c'était complexe » sous une réponse | Le routeur apprend un exemple de plus, sans entraînement. |
| 6:00 | Retour slides | Transition vers la mémoire des agents. |

Avant de monter : `make reset` (vide le cache et les compteurs) puis `make check`.

## Plan B

| Problème | Bascule |
|---|---|
| Pas d'Internet | `make down && make up TARGET=local-offline` |
| gpt-oss lent ou en erreur | Décocher « routage » n'aide pas (tout irait au grand modèle) : passer `COMPLEX_MODEL=Meta-Llama-3_3-70B-Instruct` dans l'env et `make up` |
| Le cache répond trop souvent / pas assez | Ajuster `CACHE_THRESHOLD` (0,90 par défaut ; mesuré : reformulations 0,94-0,98, question voisine 0,71) |

## Réglages utiles

| Variable | Défaut | Rôle |
|---|---|---|
| `CACHE_THRESHOLD` | 0.90 | similarité minimale pour servir une réponse du cache |
| `CACHE_TTL` | 86400 | durée de vie d'une réponse en cache (s) |
| `ROUTE_K` | 5 | nombre d'exemples qui votent |
| `ROUTE_MIN_SIMILARITY` | 0.45 | en dessous, la question ne ressemble à aucun exemple : grand modèle par prudence (ex. « Quel temps fait-il à Paris ? ») |
| `SIMPLE_MODEL` / `COMPLEX_MODEL` | Mistral Small 3.2 / gpt-oss-120b | modèles appelés |
| `MAX_TOKENS_SIMPLE` / `MAX_TOKENS_COMPLEX` | 500 / 2500 | plafonds de génération |

Les exemples du routeur sont dans `routes.yaml` (20 simples, 16 complexes, en français). Mesuré avec BGE-M3 sur AI Endpoints : « Comment supprimer une clé dans Valkey ? » → simple, « Conçois une stratégie de cache… » → complexe (vote 100 %), « Quel temps fait-il à Paris ? » → grand modèle par prudence (meilleur exemple à 0,42).

## Contenu du dossier

```
demo-3-cache-routage/
├── README.md, Makefile, docker-compose.yml
├── routes.yaml           ← exemples du routeur (simple / complexe)
├── env/                  ← local.env, local-offline.env, ovhcloud.env.example, aiven.env.example, secrets.env.example
├── cli/commandes-live.md ← commandes valkey-cli pour la scène
└── app/demo/
    ├── config.py   paramètres            ├── cache.py     cache exact + sémantique
    ├── router.py   routeur KNN (vote)    ├── stats.py     compteurs (HINCRBY)
    ├── prices.py   prix AI Endpoints     ├── llm.py       API compatible OpenAI (+ réflexion des modèles)
    ├── pipeline.py étapes d'une question ├── load.py      index + exemples + prix
    ├── check.py    vérifications         ├── server.py    API (SSE)
    └── static/index.html  interface
```

- [ ] Plan B `local-offline` : application **Ollama lancée** (`ollama list` répond) et VPN coupé, sinon le conteneur ne joint pas `host.docker.internal:11434`
