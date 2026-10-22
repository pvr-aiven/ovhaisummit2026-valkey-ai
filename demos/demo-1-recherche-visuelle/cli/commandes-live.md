# Commandes à taper en live (valkey-cli)

Ouvrir le terminal avec `make cli TARGET=ovhcloud` (ou `local`). Police du terminal en grand (≥ 20 pt).

## 1. Ce qu'il y a dans Valkey

Remplacer `<id>` par l'identifiant d'un produit affiché dans l'interface (il apparaît sous le produit de référence, ex. `product:12345`).

```
FT._LIST
HMGET product:<id> name gender category price stock
```

> « Un produit, c'est un simple hash. Il y a aussi un champ `embedding` : 512 nombres, l'image vue par le modèle CLIP. »

## 2. Créer l'index en direct (optionnel, 30 s)

Supprimer l'index (les données restent) puis le recréer :

```
FT.DROPINDEX idx:products
FT.CREATE idx:products ON HASH PREFIX 1 product: SCHEMA name TEXT gender TAG category TAG color TAG price NUMERIC stock NUMERIC embedding VECTOR HNSW 12 TYPE FLOAT32 DIM 512 DISTANCE_METRIC COSINE M 16 EF_CONSTRUCTION 200 EF_RUNTIME 64
FT.INFO idx:products
```

Relancer `FT.INFO` deux ou trois fois : `num_docs` monte tout seul (backfill), sans pipeline d'ingestion.

## 3. Filtres sans vecteur

```
FT.SEARCH idx:products "@gender:{women} @price:[-inf 60] @stock:[1 +inf]" RETURN 3 name price stock LIMIT 0 5
```

## 4. La mise à jour est immédiate

Après une recherche dans l'interface, mettre en rupture le premier résultat (ou utiliser le bouton « Rupture ») :

```
HSET product:<id> stock 0
```

Relancer la recherche filtrée « en stock » : le produit disparaît, sans réindexation.

## 5. Remise à zéro après répétition

```
make reset TARGET=ovhcloud
```
