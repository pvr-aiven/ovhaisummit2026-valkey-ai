# Démo 2 – Un assistant RAG de bout en bout

**Slide :** « Démo 2 : un assistant RAG de bout en bout » · **Durée sur scène :** 7 min · **Cibles :** `local` (Valkey Docker + AI Endpoints), `local-offline` (Valkey Docker + Ollama, sans Internet), `ovhcloud` (Managed Valkey + AI Endpoints), `aiven` (Aiven for Valkey, AI Gateway à venir)

## Ce que la démo montre

1. Une **base de connaissance** : documentation produit (OVHcloud, Aiven for Valkey, Valkey) et articles de blog (Aiven), en anglais, découpés en ~545 chunks stockés en **hashes** dans Valkey avec leur embedding **BGE-M3** (1024 dimensions).
2. Une **question en langage naturel**, en français : vectorisée par BGE-M3, comparée aux chunks par `FT.SEARCH … =>[KNN 5 …]`.
3. Une **réponse sourcée** générée par **Mistral Small 3.2** via AI Endpoints, en streaming, avec des citations `[1]`, `[2]` cliquables.
4. L'**historique de conversation dans un stream Valkey** (`XADD`, `XREVRANGE`, `EXPIRE`) : une question de suivi (« et avec plusieurs valeurs de tag ? ») est reformulée grâce à l'historique.
5. Trois comparaisons qui marquent :
   - **sans RAG** : le modèle seul répond de mémoire, souvent à côté ;
   - **plein texte** : la même question en français ne trouve rien par mots-clés dans des documents anglais, la recherche vectorielle si ;
   - **filtre de source** : `@source:{ovhcloud_docs}` combiné au KNN dans la même requête.

Le panneau **« Sous le capot »** affiche chaque étape avec sa commande (Valkey ou modèle) et son temps.

## Architecture

```
 Navigateur ──► app (FastAPI, conteneur Docker sur le portable)
                 ├─ API compatible OpenAI ──► AI Endpoints : bge-m3 (embeddings), Mistral-Small-3.2 (génération)
                 │                            ou Ollama (local-offline), ou AI Gateway Aiven (à venir)
                 └─ valkey-py ──► Valkey 9.1 + Valkey Search
                                   chunk:*      hashes (texte + embedding)   ← FT.SEARCH idx:kb
                                   chat:<id>    stream (historique, TTL 1 h)
```

Le code est le même pour toutes les cibles : seules les URL, clés et noms de modèles changent (`env/<cible>.env`).

## Prérequis

- Docker avec **Compose ≥ 2.24**, `make`
- Une **clé AI Endpoints** (Control Panel OVHcloud > Public Cloud > AI Endpoints > API keys), à mettre dans `env/secrets.env`. Sans clé, l'accès anonyme est limité à 2 requêtes par minute : insuffisant pour charger la base.
- Pour le plan B hors ligne : [Ollama](https://ollama.com) installé sur le portable, puis `make ollama` (télécharge `bge-m3` et `mistral`, ~5 Go)

## Mode opératoire

### A. Cible locale (Valkey Docker + AI Endpoints) : à utiliser par défaut

```bash
cd demos/demo-2-rag
cp env/secrets.env.example env/secrets.env      # puis coller la clé AI Endpoints
make prepare      # build + téléchargement des sources + vectorisation + index + vérifications (~3 min)
make up           # → http://localhost:8001
```

`make check` doit tout afficher en vert : Valkey, index, embedding (1024 dimensions), recherche KNN avec score, génération.

### B. Plan B sans Internet (Valkey Docker + Ollama)

À préparer **la veille**, avec une connexion :

> Ollama tronque sans prévenir les prompts plus longs que son contexte (2 048 à 4 096 tokens selon la version). Le prompt RAG en fait ~3 000 : lancer Ollama avec `OLLAMA_CONTEXT_LENGTH=8192` (macOS : `launchctl setenv OLLAMA_CONTEXT_LENGTH 8192`, puis relancer l'application).

```bash
make ollama                              # modèles dans Ollama
make prepare TARGET=local-offline        # index séparé idx:kb_offline, vectorisé par Ollama
```

Le jour J, si le réseau tombe : `make up TARGET=local-offline`. Les réponses sont plus lentes et un peu moins bonnes (Mistral 7B au lieu de Mistral Small 24B) : le dire simplement.

### C. Cible OVHcloud (Managed Valkey 9.1 + AI Endpoints)

```bash
cp env/ovhcloud.env.example env/ovhcloud.env       # VALKEY_URL rediss://… du service managé
make prepare TARGET=ovhcloud && make up TARGET=ovhcloud
```

Mêmes réglages réseau que la démo 1 : IP autorisée, utilisateur avec les commandes `FT.*` et `X*`, TLS.

### D. Cible Aiven (prête, à valider)

```bash
cp env/aiven.env.example env/aiven.env   # Service URI + CA du projet dans ./certs/aiven-ca.pem
make prepare TARGET=aiven && make up TARGET=aiven
```

En attendant l'AI Gateway, cette cible garde les modèles AI Endpoints. Quand l'AI Gateway sera disponible, il suffira de renseigner `EMBED_BASE_URL`, `CHAT_BASE_URL`, les clés et les noms de modèles, puis `make load TARGET=aiven` (les vecteurs doivent venir du même service que les requêtes).

## Déroulé sur scène (7 min)

| Temps | Action | Ce qu'on dit |
|---|---|---|
| 0:00 | Interface ouverte, panneau « Sous le capot » vide | « 545 morceaux de documentation OVHcloud, Aiven et Valkey, plus le blog Aiven, en anglais, dans Valkey avec leur vecteur BGE-M3. » |
| 0:30 | Cocher **sans RAG**, demander « Comment faire une recherche hybride avec un filtre dans Valkey ? » | « Le modèle seul répond de mémoire : plausible, mais rien ne garantit que c'est juste. » |
| 1:30 | Décocher, reposer la même question | Montrer les étapes : vecteur de la question, `FT.SEARCH … KNN 5`, extraits et scores, prompt, génération streamée. Cliquer sur une citation `[2]`. |
| 3:00 | Juste après la question sur la recherche hybride, question de suivi : « Et avec plusieurs valeurs de tag ? » | Étape **reformulation** : l'historique relu dans le stream Valkey (`XREVRANGE`) la transforme en « Comment faire une recherche hybride avec un filtre sur plusieurs valeurs de tag dans Valkey ? ». Extrait trouvé : *Multiple Tag Query*, syntaxe `@champ:{a | b}`. |
| 4:00 | Cocher **comparer au plein texte**, poser une autre question en français | « Par mots-clés : 0 résultat, les documents sont en anglais. En vecteurs, BGE-M3 relie le français et l'anglais. » |
| 5:00 | Filtre **Docs OVHcloud**, demander « Comment me connecter en Python à un Valkey managé ? » | « Le filtre de source est un TAG dans la même requête que le KNN : c'est comme ça qu'on applique des droits d'accès. » |
| 5:30 | *(Effet)* Même question avec le filtre **Blog Aiven** seul | Étape **garde-fou** : aucun extrait au-dessus du seuil, réponse refusée **sans appeler le modèle**. « Il ne peut pas inventer à partir de sources auxquelles il n'a pas droit. » |
| 5:45 | *(Optionnel)* terminal : `XRANGE chat:<id> - +` et `TTL chat:<id>` (voir `cli/commandes-live.md`) | « L'historique est un stream Valkey qui expire tout seul. » |
| 6:30 | Retour slides | Transition vers le cache sémantique (démo 3). |

Avant de monter sur scène : `make reset`, `make check`, page ouverte et zoom à 125 %.

## Checklist

**La veille**
- [ ] `make prepare` (cible du jour) tout vert, puis `make prepare TARGET=local-offline` (plan B)
- [ ] Répétition chronométrée avec les questions du déroulé ; noter les réponses obtenues
- [ ] Captures d'écran des étapes clés dans `plan-b/`

**Une heure avant**
- [ ] Plan B `local-offline` : application **Ollama lancée** (`ollama list` répond) et VPN coupé, sinon le conteneur ne joint pas `host.docker.internal:11434`
- [ ] `make check` (latence génération affichée), `make reset`, `make up`
- [ ] Onglet ouvert sur http://localhost:8001, terminal `make cli` prêt

## Plan B

| Problème | Bascule |
|---|---|
| Pas d'Internet | `make down && make up TARGET=local-offline` |
| AI Endpoints lent ou en erreur | Idem, ou montrer les captures `plan-b/` |
| Réponse surprenante en live | C'est l'occasion de montrer les sources : « le modèle s'appuie sur ces extraits, voyez ce qu'il a reçu » (dérouler le prompt) |

## Dépannage

| Symptôme | Cause probable | Solution |
|---|---|---|
| `403 authentication failed` | Clé AI Endpoints absente ou expirée | Renseigner `env/secrets.env`, régénérer la clé |
| `quota atteint` au chargement | Accès anonyme (2 req/min) | Configurer la clé |
| `given batch size overflow maximal one` | Plus de 25 textes par appel d'embedding | Garder `EMBED_BATCH` ≤ 25 (16 par défaut) |
| « index vectorisé avec un autre modèle » | Base chargée avec un autre service d'embedding | `make load` avec la bonne cible |
| Ollama injoignable (`local-offline`) | Application Ollama non lancée | Lancer Ollama, `ollama list` doit montrer bge-m3 et mistral |
| Réponses hors sujet en `local-offline` | Contexte Ollama trop court | `OLLAMA_CONTEXT_LENGTH=8192` puis relancer Ollama |
| Le plein texte n'est pas proposé | Serveur sans recherche TEXT (valkey-search < 1.2) | Normal : le reste fonctionne |

## Rôle de l'historique

L'historique (stream `chat:<id>`) sert **uniquement à reformuler** la question de suivi (« et sur Aiven ? » → « Comment gérer la connexion SSL avec Aiven ? »). Il n'est **pas** redonné au modèle au moment de générer la réponse : seuls les extraits et la question reformulée le sont. Sinon le modèle recopie sa réponse précédente (par exemple la procédure OVHcloud) même quand les extraits, filtrés sur « Docs Aiven », disent autre chose.

## Diversité des extraits

Valkey renvoie 15 candidats (`KNN_CANDIDATES`), puis l'application en garde 5 (`TOP_K`) : au plus 2 par page (`MAX_PER_DOC`) et, quand aucune source n'est imposée, au plus 3 par source (`MAX_PER_SOURCE`). Sans cela, une question comme « Comment gérer la connexion SSL avec Valkey sur OVHcloud et Aiven ? » ne recevait que la page Aiven sur le SSL, la plus proche, et la réponse oubliait OVHcloud. Le panneau « Sous le capot » affiche les candidats écartés avec la raison (*seuil*, *même page*, *même source*). Quand les extraits couvrent plusieurs produits, le modèle répond en une partie par produit.

## Garde-fou de similarité

Les extraits dont la similarité avec la question est inférieure à `MIN_SIMILARITY` (0,60 par défaut) ne sont pas donnés au modèle. S'il n'en reste aucun, l'application répond « Je ne trouve pas cette information dans les sources autorisées » sans appeler le modèle. Sans ce garde-fou, un modèle (surtout un petit, comme Mistral 7B en `local-offline`) complète volontiers avec sa mémoire, même quand le filtre ne lui a donné que des extraits hors sujet.

Mesuré avec BGE-M3 (AI Endpoints) sur « Comment me connecter en Python à un Valkey managé chez OVHcloud ? » : extraits pertinents de la doc OVHcloud entre 0,65 et 0,76, meilleur extrait du blog Aiven à 0,56. À recalibrer sur vos questions de répétition (`MIN_SIMILARITY` dans `env/<cible>.env`, 0 pour désactiver). Le panneau « Sous le capot » affiche les extraits écartés en grisé.

## Catalogue et prix des modèles AI Endpoints

Deux sources spéciales de `sources.yaml` décrivent tous les modèles AI Endpoints :

- `kind: ai-endpoints-catalog` : l'API publique du catalogue (`catalog.endpoints.ai.ovh.net`) transformée en une section par modèle (catégorie, éditeur, licence, entrées / sorties, function calling, raisonnement, contexte, dimension des vecteurs). Les prix n'en sont pas repris.
- `kind: html-section` : la section `#ai-endpoints` de la [page des prix Public Cloud](https://www.ovhcloud.com/en/public-cloud/prices/#ai-endpoints), qui fait foi pour les tarifs. Chaque ligne de tableau devient une phrase autonome (« Mistral-Small-3.2-24B-Instruct-2506 : Price (excl. VAT / 1M input tokens): $0.10; … »).

Les deux sont relues à chaque `make ingest` : relancer `make ingest && make load` la veille pour avoir les tarifs du jour. La page des prix liste parfois des modèles absents du catalogue (et inversement) : c'est l'état réel des deux sources.

## Personnaliser la base de connaissance

- Ajouter ou retirer des pages dans `sources.yaml` (Markdown ou HTML), puis `make ingest && make load`.
- Déposer ses propres fichiers `.md` / `.txt` dans `data/corpus/local/` : ils apparaissent avec la source « Mes documents ».
- Licences : la documentation Valkey est sous CC BY-SA 4.0 (les liens sources sont affichés à chaque réponse) ; documentation OVHcloud, documentation et blog Aiven sont cités avec leur lien. À vérifier avant une diffusion publique de captures.

## Contenu du dossier

```
demo-2-rag/
├── README.md, Makefile, docker-compose.yml
├── sources.yaml            ← pages qui composent la base de connaissance
├── env/                    ← local.env, local-offline.env, ovhcloud.env.example, aiven.env.example, secrets.env.example
├── cli/commandes-live.md   ← commandes valkey-cli pour la scène
├── data/                   ← corpus téléchargé, chunks.jsonl, cache des embeddings (généré)
└── app/demo/
    ├── config.py      paramètres          ├── kb.py       index, KNN, plein texte
    ├── ingest.py      sources → chunks    ├── history.py  stream chat:<id>
    ├── llm.py         API compatible OpenAI (embeddings, génération)
    ├── load.py        vectorisation + HSET + FT.CREATE
    ├── rag.py         pipeline pas à pas  ├── check.py    vérifications
    ├── server.py      API (streaming SSE) └── static/index.html  interface
```
