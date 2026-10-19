# Development tasks. Run `make` or `make help` to list them.
SHELL := /bin/bash
COMPOSE := docker compose

.DEFAULT_GOAL := help
.PHONY: help up down rebuild reset shell

help: ## Show the available tasks
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  make %-8s %s\n", $$1, $$2}'

up: ## Start the services in the background
	$(COMPOSE) up -d

down: ## Stop the services (keeps the database)
	$(COMPOSE) down

rebuild: ## Rebuild the images without cache and restart (keeps the database)
	$(COMPOSE) build --no-cache
	$(COMPOSE) up -d --force-recreate

reset: ## Recreate everything from scratch, DELETING the database
	@read -p "This deletes the database. Type 'yes' to continue: " answer; \
		[ "$$answer" = "yes" ] || { echo "Cancelled."; exit 1; }
	$(COMPOSE) down --volumes --remove-orphans
	$(COMPOSE) build --no-cache
	$(COMPOSE) up -d

shell: ## Open a bash shell in the api container
	$(COMPOSE) exec api bash
