# Démo 2 – Assistant RAG avec Valkey
# make <commande> TARGET=local (défaut) | local-offline | ovhcloud | aiven
#   local          Valkey 9.1 dans Docker + AI Endpoints
#   local-offline  Valkey 9.1 dans Docker + Ollama, sans Internet
#   ovhcloud       OVHcloud Managed Valkey 9.1 + AI Endpoints   (env/ovhcloud.env)
#   aiven          Aiven for Valkey (+ AI Gateway)                (env/aiven.env)
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
URL := http://localhost:8001
# ---------------------------------------------------------------------------------------------

.DEFAULT_GOAL := help
.PHONY: help env build prepare load reindex reset check up down logs cli test ollama ingest ingest-offline reset-history

help: ## Affiche cette aide
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'
	@echo "  Cibles : $(TARGETS)"
	@echo "  Cible courante : TARGET=$(TARGET)  (fichier $(ENV_FILE))"

env:
	@# Cibles locales : env/<cible>.env créé automatiquement depuis l'exemple (aucun .env n'est versionné)
	@if [ ! -f $(ENV_FILE) ] && [ -n "$(filter local local-offline,$(TARGET))" ]; then cp $(ENV_FILE).example $(ENV_FILE) && echo "→ $(ENV_FILE) créé depuis $(ENV_FILE).example"; fi
	@test -f $(ENV_FILE) || (echo "✘ $(ENV_FILE) absent : copier $(ENV_FILE).example et le compléter" && exit 1)
	@test -f env/secrets.env || echo "! env/secrets.env absent : pas de clé AI Endpoints (accès anonyme très limité)"

# ---- commandes communes aux démos ----------------------------------------------------------
build: env ## Construit l'image de l'application
	$(COMPOSE) build app

prepare: env build ingest load check ## Tout préparer d'un coup (la veille, avec une bonne connexion)

load: env ## Vectorise les chunks, les écrit dans Valkey et crée l'index
	$(RUN) python -m demo.load --flush

reindex: env ## Recrée l'index (données conservées)
	$(RUN) python -m demo.load --reindex

reset: env ## Avant de monter sur scène : supprime toutes les conversations (clés chat:*)
	$(RUN) python -m demo.history

check: env ## Vérifie Valkey, index, embedding, génération et latences
	$(RUN) python -m demo.check

up: env ## Lance l'interface
	$(COMPOSE) up -d --build app
	@echo "→ $(URL)  (cible : $(TARGET))"

down: ## Arrête les conteneurs (les données Valkey locales sont conservées)
	docker compose --profile local --profile tools down

logs: ## Journaux de l'application
	$(COMPOSE) logs -f app

cli: env ## Ouvre valkey-cli sur la cible courante
	$(COMPOSE) --profile tools run --rm cli

test: build ## Tests unitaires (sans Valkey ni modèles ; pip install pytest demande Internet)
	docker compose run --rm --no-deps -v "$(CURDIR)/app/tests:/srv/tests:ro" app sh -c "pip install -q pytest && PYTHONPATH=.:tests python -m pytest -q -p no:cacheprovider tests"

ollama: ## Télécharge les modèles de local-offline dans Ollama (sur le portable)
	ollama pull bge-m3 && ollama pull mistral
	@echo "Rappel : contexte Ollama à 8192 tokens (launchctl setenv OLLAMA_CONTEXT_LENGTH 8192 puis relancer Ollama)"

# ---- propre à cette démo -------------------------------------------------------------------
ingest: env ## Télécharge les sources (sources.yaml) et les découpe en chunks
	$(RUN) python -m demo.ingest

ingest-offline: env ## Re-découpe le corpus déjà téléchargé, sans réseau
	$(RUN) python -m demo.ingest --offline

reset-history: reset ## (ancien nom de reset)
