# Démo 3 – Cache et routage sémantiques avec Valkey
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
URL := http://localhost:8002
# ---------------------------------------------------------------------------------------------

.DEFAULT_GOAL := help
.PHONY: help env build prepare load reindex reset check up down logs cli test ollama prices

help: ## Affiche cette aide
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'
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

prepare: env build load check ## Tout préparer d'un coup (index, exemples de routage, prix du jour, vérifications)

load: env ## Crée les index et charge les exemples de routage (routes.yaml) + prix du jour
	$(RUN) python -m demo.load

reindex: env ## Recrée les index et revectorise les exemples du routeur (après un changement de modèle d'embedding)
	$(RUN) python -m demo.load --reset

reset: env ## Avant de monter sur scène : vide le cache, remet les compteurs à zéro, recharge le routeur
	$(RUN) python -m demo.load --reset

check: env ## Vérifie Valkey, index, routage et les deux modèles
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

test: build ## Tests unitaires (sans Valkey ni modèles)
	docker compose run --rm --no-deps -v "$(CURDIR)/app/tests:/srv/tests:ro" app sh -c "pip install -q pytest && PYTHONPATH=.:tests python -m pytest -q -p no:cacheprovider tests"

ollama: ## Télécharge les modèles de local-offline dans Ollama (sur le portable)
	ollama pull bge-m3 && ollama pull mistral && ollama pull gpt-oss:20b

# ---- propre à cette démo -------------------------------------------------------------------
prices: env ## Met à jour les prix AI Endpoints depuis la page des prix OVHcloud
	$(RUN) python -m demo.prices
