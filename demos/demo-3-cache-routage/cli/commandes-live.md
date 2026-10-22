# Commandes à taper en live (valkey-cli)

Ouvrir le terminal avec `make cli` (ou `make cli TARGET=ovhcloud`). Police ≥ 20 pt.

## 1. Le cache

```
FT.INFO idx:cache
SCAN 0 MATCH cache:* COUNT 100
HMGET cache:<id> question model tokens_out cost
TTL cache:<id>
```

> « Une réponse en cache = un hash : la question, la réponse, son vecteur, ce qu'elle a coûté. Elle expire seule. »

## 2. Le routeur

```
FT.SEARCH idx:route "@label:{complex}" RETURN 1 text LIMIT 0 5
```

## 3. Les compteurs

```
HGETALL stats:demo3
```

## 4. Remise à zéro avant la scène

```
make reset
```
