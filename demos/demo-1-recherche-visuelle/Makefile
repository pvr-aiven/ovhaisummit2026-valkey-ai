# Démo 1 – Recherche visuelle et hybride avec Valkey
# make <commande> TARGET=local (défaut) | local-offline | ovhcloud | aiven
#   local          Valkey 9.1 dans Docker
#   local-offline  idem, sans Internet (modèles CLIP lus depuis le cache)
#   ovhcloud       OVHcloud Managed Valkey 9.1          (env/ovhcloud.env)
#   aiven          Aiven for Valkey                     (env/aiven.env)
# ---- en-tête commun aux démos --------------------------------------------------------------
TARGETS := local local-offline ovhcloud aiven
TARGET ?= local
override TARGET := $(patsubst ovh,ovhcloud,$(TARGET))
ifeq ($(filter $(TARGET),$(TARGETS)),)
$(error TARGET=$(TARGET) inconnue. Valeurs possibles : $(TARGETS))
endif
export ENV_FILE := env/$(TARGET).env
PROFILE := $(if $(filter local local-offline,$(TARGET)),--profile local,)
COMPOSE := docker compose $(PROFILE)
RUN := $(COMPOSE) run --rm --build app
URL := http://localhost:8000
# ---------------------------------------------------------------------------------------------
# Hors ligne : automatique en local-offline ; OFFLINE=1 l'active aussi sur une cible distante (sur scène)
export OFFLINE ?= $(if $(filter local-offline,$(TARGET)),1,0)

.DEFAULT_GOAL := help
.PHONY: help env build prepare load reindex reset check up down logs cli test ollama dataset warmup

help: ## Affiche cette aide
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'
	@echo "  Cibles : $(TARGETS)"
	@echo "  Cible courante : TARGET=$(TARGET)  (fichier $(ENV_FILE), hors ligne : $(OFFLINE))"

env:
	@# Cibles locales : env/<cible>.env créé automatiquement depuis l'exemple (aucun .env n'est versionné)
	@if [ ! -f $(ENV_FILE) ] && [ -n "$(filter local local-offline,$(TARGET))" ]; then cp $(ENV_FILE).example $(ENV_FILE) && echo "→ $(ENV_FILE) créé depuis $(ENV_FILE).example"; fi
	@test -f $(ENV_FILE) || (echo "✘ $(ENV_FILE) absent : copier $(ENV_FILE).example et le compléter" && exit 1)

# ---- commandes communes aux démos ----------------------------------------------------------
build: env ## Construit l'image de l'application
	$(COMPOSE) build app

prepare: env build dataset warmup load check ## Tout préparer d'un coup (la veille, avec une bonne connexion)

load: env ## Calcule les embeddings, écrit les hashes et crée l'index
	$(RUN) python -m demo.load

reindex: env ## Recrée l'index (les données restent en place)
	$(RUN) python -m demo.load --reindex

reset: env ## Avant de monter sur scène : remet le catalogue dans son état initial (stocks compris)
	$(RUN) python -m demo.load

check: env ## Vérifie connexion, module Search, index et latence
	$(RUN) python -m demo.check

up: env ## Lance l'interface
	$(COMPOSE) up -d --build app
	@echo "→ $(URL)  (cible : $(TARGET), hors ligne : $(OFFLINE))"

down: ## Arrête les conteneurs (les données Valkey locales sont conservées)
	docker compose --profile local --profile tools down

logs: ## Journaux de l'application
	$(COMPOSE) logs -f app

cli: env ## Ouvre valkey-cli sur la cible courante
	$(COMPOSE) --profile tools run --rm cli

test: build ## Tests unitaires (sans Valkey ni modèles)
	docker compose run --rm --no-deps -v "$(CURDIR)/app/tests:/srv/tests:ro" app sh -c "pip install -q pytest && PYTHONPATH=.:tests python -m pytest -q -p no:cacheprovider tests"

ollama: ## (Rien à faire ici : CLIP tourne dans le conteneur ; `make warmup` suffit pour local-offline)
	@echo "Démo 1 : aucun modèle Ollama. Pour local-offline : make warmup (avec réseau), puis make up TARGET=local-offline"

# ---- propre à cette démo -------------------------------------------------------------------
# Téléchargements : toujours avec réseau, même si TARGET=local-offline
dataset warmup: OFFLINE := 0

dataset: env ## Télécharge le catalogue de chaussures et ses images dans ./data
	$(RUN) python -m demo.prepare_dataset

warmup: env ## Télécharge les modèles CLIP dans le cache (indispensable avant local-offline)
	$(RUN) python -c "from demo.embeddings import warmup; warmup(); print('Modèles prêts')"
