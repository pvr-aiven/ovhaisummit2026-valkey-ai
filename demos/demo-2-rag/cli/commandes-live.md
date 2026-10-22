# Commandes à taper en live (valkey-cli)

Ouvrir le terminal avec `make cli` (ou `make cli TARGET=ovhcloud`). Police du terminal en grand (≥ 20 pt).

## 1. La base de connaissance

```
FT.INFO idx:kb
HMGET chunk:<id> title section source text
```

Le `<id>` d'un chunk s'obtient avec `FT.SEARCH idx:kb "@source:{aiven_blog}" RETURN 1 title LIMIT 0 3`.

> « Un morceau de documentation = un hash : le texte, sa source, son titre et son vecteur de 1 024 nombres. »

## 2. L'historique de la conversation

L'identifiant de session est affiché en haut à droite de l'interface (`chat:…`).

```
XRANGE chat:<session> - +
XLEN chat:<session>
TTL chat:<session>
```

> « Chaque question et chaque réponse est une entrée du stream. La conversation expire toute seule après une heure d'inactivité. »

## 3. Remise à zéro

```
make reset
```
