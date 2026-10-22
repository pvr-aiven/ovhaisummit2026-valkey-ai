# Démo 1 – Recherche visuelle et hybride avec Valkey

**Slide :** « Démo 1 : recherche visuelle et hybride » · **Durée sur scène :** 6 min · **Cibles :** `local` (Valkey Docker), `local-offline` (idem, sans Internet), `ovhcloud` (Managed Valkey 9.1), `aiven` (Aiven for Valkey)

## Ce que la démo montre

1. Un catalogue de chaussures stocké en **hashes** dans Valkey, chaque produit avec l'**embedding** de son image (512 dimensions, modèle CLIP).
2. Un index **HNSW** créé avec `FT.CREATE`, qui se remplit tout seul à partir des données existantes.
3. « **Trouve-moi des chaussures qui ressemblent à celle-ci** » : recherche par similarité (KNN) à partir d'un produit ou d'une photo prise sur scène.
4. La **même requête filtrée** par genre, prix et stock, **en un seul aller-retour** (`FT.SEARCH … (filtres)=>[KNN …]`).
5. Un `HSET` qui met un produit en rupture : il disparaît immédiatement des résultats filtrés.

L'interface affiche à chaque action la **commande exacte envoyée à Valkey** et sa latence.

### Onglet « Comment ça marche »

Un second onglet (http://localhost:8000/comment-ca-marche) explique **la dernière recherche** en 8 étapes animées, avec les vraies données (vecteur, hash, comptages, résultats) :

| # | Étape | Ce qu'on voit |
|---|---|---|
| 1 | Image → vecteur | L'image passe dans CLIP ; ses 512 valeurs s'affichent en carte de chaleur |
| 2 | Stockage en hash | Le `HSET` réel du produit et le hash obtenu, embedding compris |
| 3 | Indexation | Chaque champ alimente son index : TAG, NUMERIC, VECTOR (HNSW) ; le `FT.CREATE` complet |
| 4 | Espace vectoriel | Les 3 000 produits projetés en 2D (ACP), la référence et ses voisins reliés, avec ou sans filtres, zoom possible |
| 5 | La requête | La commande `FT.SEARCH` découpée en morceaux colorés, chacun expliqué |
| 6 | Filtrer | L'entonnoir des filtres, compté en direct dans Valkey (ex. 3 000 → 1 200 → 800 → 640) |
| 7 | HNSW | En 7 sous-étapes (→ pour avancer) : les 3 niveaux comme les mêmes produits à 3 échelles, entrée par le haut, grands sauts, descente sur le même point, quartier exact au niveau 0, exploration locale avec filtres, bilan en log(N) |
| 8 | Résultat | Similarité pure et hybride côte à côte, distance cosinus → similarité |

Navigation : flèches ← → du clavier, Page précédente / suivante (compatible télécommande de présentation), ou la liste des étapes. La barre du bas montre en permanence la commande, avec en couleur la partie concernée par l'étape. Si aucune recherche filtrée n'a été faite, l'onglet utilise un exemple (femme, ≤ 100 €, en stock). L'onglet « Recherche » ramène sur la même recherche.

Deux usages possibles sur scène : juste après la démo (2 min, étapes 4 à 7), ou en remplacement des slides techniques si le temps manque.

## Architecture

```
 Navigateur ──► app (FastAPI, conteneur Docker sur le portable)
                 ├─ CLIP ViT-B/32 (image → vecteur 512)            ┐ modèles open source,
                 ├─ CLIP multilingue (texte FR → même espace)      ┘ exécutés en local (CPU)
                 └─ valkey-py ──► Valkey 9.1 + Valkey Search
                                   local, local-offline : conteneur valkey-bundle
                                   ovhcloud             : Managed Valkey (TLS)
                                   aiven                : Aiven for Valkey (TLS)
```

Pourquoi les embeddings sont calculés en local : le catalogue AI Endpoints (vérifié le 7 octobre 2026) ne propose que des modèles d'embedding **texte** (BGE-M3, bge-multilingual-gemma2, Qwen3-Embedding-8B). Pour des images, on utilise CLIP, open source, dans le conteneur. Seul Valkey change d'une cible à l'autre.

## Prérequis

- Docker Desktop (ou Docker Engine) avec **Compose ≥ 2.24** (`docker compose version`)
- ~6 Go d'espace disque (image Python + PyTorch CPU, modèles, images)
- Une bonne connexion **pour la préparation uniquement** (dataset et modèles). Le jour J, la démo tourne sans Internet en cible locale ; en cible OVH, seule la connexion à Valkey est nécessaire.
- `make` (présent sur macOS et Linux)

## Mode opératoire

### A. Cible locale (répétitions, plan B)

```bash
cd demos/demo-1-recherche-visuelle
make prepare          # build + dataset + embeddings + index + vérifications (10-15 min la 1re fois)
make up               # → http://localhost:8000
```

`make check` doit tout afficher en vert. `make cli` ouvre valkey-cli sur le Valkey local.

### A bis. Cible locale sans Internet (`local-offline`)

Même Valkey local, mais les modèles CLIP sont lus **uniquement depuis le cache** (`HF_HUB_OFFLINE=1`) : aucun appel à Hugging Face. À faire une fois avec du réseau : `make prepare` (ou `make warmup`). Ensuite :

```bash
make up TARGET=local-offline
```

Les commandes `dataset` et `warmup` gardent l'accès réseau même avec `TARGET=local-offline`. Sur une cible distante, `OFFLINE=1` active le même comportement (ex. `make up TARGET=ovhcloud OFFLINE=1`).

### B. Cible OVHcloud Managed Valkey 9.1

1. **Créer le service** (Control Panel > Public Cloud > Databases & Analytics > Créer) : moteur **Valkey 9.1**, région proche de Paris (ex. GRA ou SBG), plan au choix (1 nœud suffit pour la démo, 3 nœuds pour montrer la HA).
2. **Autoriser votre IP** : onglet « IP autorisées », ajouter l'IP publique du portable (et celle du réseau de la salle le jour J, ou `0.0.0.0/0` temporairement si l'IP de la salle est inconnue, à retirer après le talk).
3. **Utilisateur** : onglet « Utilisateurs », créer un utilisateur (ou réinitialiser le mot de passe) avec les droits de lecture/écriture et les commandes `FT.*`.
4. **Récupérer l'hôte et le port** (onglet « Informations générales ») et, si proposé, le **certificat CA** à déposer dans `./certs/`.
5. Configurer la cible :
   ```bash
   cp env/ovhcloud.env.example env/ovhcloud.env    # puis compléter VALKEY_URL (rediss://…)
   make prepare TARGET=ovhcloud
   make up TARGET=ovhcloud
   ```
6. `make check TARGET=ovhcloud` vérifie la connexion TLS, la version 9.x et la **présence du module Search**. Si le module n'apparaît pas, l'activer dans la configuration avancée du service ou contacter OVHcloud.

> Les libellés exacts du Control Panel sont à confirmer lors de la création du service : je n'ai pas pu les vérifier.

Le dataset et les embeddings déjà calculés en local sont réutilisés (dossier `./data`) : seul le chargement dans Valkey est refait.

### C. Cible Aiven for Valkey (prête, à valider)

Le module Search est activé par défaut sur Aiven for Valkey 9.x.

```bash
cp env/aiven.env.example env/aiven.env   # Service URI de la console Aiven
# + télécharger le « CA certificate » du projet dans ./certs/aiven-ca.pem (obligatoire)
make prepare TARGET=aiven && make up TARGET=aiven
```

La démo 1 n'appelle aucune API d'IA externe : l'AI Gateway n'est pas nécessaire ici (elle le sera pour les démos 2 et 3).

## Déroulé sur scène (6 min)

| Temps | Action | Ce qu'on dit |
|---|---|---|
| 0:00 | Interface ouverte sur le catalogue, cible **ovhcloud** visible en haut | « Un catalogue de 3 000 chaussures, stocké dans un Managed Valkey 9.1 chez OVHcloud. Chaque produit est un simple hash. » |
| 0:45 | *(Optionnel)* terminal : `FT.INFO idx:products` (voir `cli/commandes-live.md`) | « L'index HNSW a été créé sur des données déjà présentes : il s'est rempli tout seul. » |
| 1:30 | Cliquer sur une basket homme | « Trouve-moi des chaussures qui ressemblent à celle-ci. » Montrer les scores et la commande `*=>[KNN 12 …]`, latence en ms. |
| 2:30 | Activer **Mode hybride**, choisir **Femme**, prix max **100 €**, **En stock** | « Même requête, mais je veux une chaussure pour femme, à moins de 100 €, disponible. » Montrer la commande : filtres + KNN dans **une seule** requête. |
| 3:45 | Bouton **Rupture** sur le premier résultat | « Le stock change : un `HSET`, et le produit disparaît du résultat. Pas de batch, pas de réindexation. » |
| 4:30 | *(Effet)* glisser une photo prise avec son téléphone, ou taper « baskets rouges pour courir » | « Le même espace vectoriel accepte une photo ou une phrase en français. » |
| 5:30 | Retour slide | Transition vers le RAG. |

Avant de monter sur scène : `make reset TARGET=ovhcloud` (remet les stocks), puis `make up TARGET=ovhcloud OFFLINE=1` (modèles depuis le cache, aucun appel à Hugging Face).

## Checklist

**La veille**
- [ ] `make prepare TARGET=ovhcloud` puis `make check TARGET=ovhcloud` tout vert
- [ ] `make prepare TARGET=local` réussi (plan B)
- [ ] Répétition complète du déroulé, chronométrée
- [ ] Captures d'écran des 4 étapes clés dans `plan-b/` (catalogue, similarité, hybride, rupture)
- [ ] Zoom du navigateur à 125-150 %, police du terminal ≥ 20 pt

**Une heure avant**
- [ ] IP du réseau de la salle ajoutée aux IP autorisées OVH
- [ ] `make check TARGET=ovhcloud` (latence affichée)
- [ ] `make reset TARGET=ovhcloud` puis `make up TARGET=ovhcloud OFFLINE=1`
- [ ] Onglet navigateur ouvert sur http://localhost:8000, terminal `make cli TARGET=ovhcloud` prêt

## Plan B

| Problème | Bascule |
|---|---|
| Pas de réseau / OVH injoignable | `make down && make up TARGET=local-offline` : même démo sur le Valkey local, sans Internet, en 20 s. Le dire simplement : « même code, Valkey local ». |
| Docker ne démarre pas | Dérouler les captures de `plan-b/` |
| Latence élevée affichée (Wi-Fi de la salle) | Le dire : c'est l'aller-retour réseau ; la recherche elle-même prend quelques ms côté serveur. |

## Dépannage

| Symptôme | Cause probable | Solution |
|---|---|---|
| `Connexion impossible` sur OVH | IP non autorisée ou URL sans TLS | Ajouter l'IP, utiliser `rediss://` |
| `certificate verify failed` | CA non reconnu | Déposer le CA dans `./certs/` et renseigner `VALKEY_CA_CERT` |
| `unknown command FT.CREATE` | Module Search absent | Vérifier la version (9.x) et l'activation du module |
| `champ TEXT non supporté` au chargement | valkey-search < 1.2 | Normal : la recherche plein texte est désactivée, le reste fonctionne |
| Première recherche lente (10-20 s) | Modèles non encore chargés | `make warmup`, attendre la fin du démarrage (`make logs`) |
| `num_docs` reste à 0 | Préfixe de clés différent | Vérifier `KEY_PREFIX` et `FT.INFO` |

## Personnaliser le catalogue

Les images du jeu public *Fashion Product Images (Small)* font environ **60 × 80 pixels** : suffisant pour la similarité, un peu flou sur grand écran. Pour la version finale, vous pouvez fournir votre propre catalogue en haute définition :

```bash
# CSV : id,name,gender,category,color,image[,price,stock]   (image = nom de fichier dans le dossier)
mkdir -p data/source && cp mon_catalogue.csv data/source/ && cp -r mes_images data/source/
docker compose run --rm app python -m demo.prepare_dataset --source csv --csv /data/source/mon_catalogue.csv --images-dir /data/source/mes_images
make load
```

Vérifier la licence des images utilisées en public (jeu Hugging Face `ashraq/fashion-product-images-small`, issu de Kaggle).

## Contenu du dossier

```
demo-1-recherche-visuelle/
├── README.md               ← ce mode opératoire
├── Makefile                ← make help
├── docker-compose.yml      ← valkey (local), app, cli
├── env/                    ← local.env, local-offline.env, ovhcloud.env.example, aiven.env.example
├── cli/commandes-live.md   ← commandes valkey-cli à taper sur scène
├── plan-b/                 ← captures d'écran de secours (à produire)
├── certs/                  ← CA des services managés (non versionné)
├── data/                   ← images, catalog.csv, embeddings.npy (généré)
└── app/
    ├── Dockerfile, requirements.txt
    ├── demo/
    │   ├── config.py           paramètres (variables d'environnement)
    │   ├── valkey_client.py    connexion locale / TLS
    │   ├── embeddings.py       CLIP image + texte multilingue
    │   ├── catalog.py          FT.CREATE, requêtes hybrides, lecture des réponses
    │   ├── prepare_dataset.py  catalogue de chaussures (HF ou CSV)
    │   ├── load.py             embeddings + HSET + index
    │   ├── check.py            vérifications avant démo
    │   ├── server.py           API
    │   └── static/index.html   interface
    └── tests/                  tests unitaires (sans Valkey)
```
