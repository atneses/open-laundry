# Development tasks. Run `make` or `make help` to list them.
SHELL := /bin/bash
COMPOSE := docker compose
CONFIRM_DELETE_DB := read -p "This deletes the database. Type 'yes' to continue: " answer; \
	[ "$$answer" = "yes" ] || { echo "Cancelled."; exit 1; }

.DEFAULT_GOAL := help
.PHONY: help up down rebuild reset resetdb shell makemigrations migrate seed

help: ## Show the available tasks
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  make %-15s %s\n", $$1, $$2}'

up: ## Start the services in the background
	$(COMPOSE) up -d

down: ## Stop the services (keeps the database)
	$(COMPOSE) down

rebuild: ## Rebuild the images without cache and restart (keeps the database)
	$(COMPOSE) build --no-cache
	$(COMPOSE) up -d --force-recreate

reset: ## Recreate everything from scratch, DELETING the database
	@$(CONFIRM_DELETE_DB)
	$(COMPOSE) down --volumes --remove-orphans
	$(COMPOSE) build --no-cache
	$(COMPOSE) up -d

resetdb: ## Delete the database and start again with an empty one (keeps the images)
	@$(CONFIRM_DELETE_DB)
	$(COMPOSE) down --volumes
	$(COMPOSE) up -d

shell: ## Open a bash shell in the api container
	$(COMPOSE) exec api bash

makemigrations: ## Create migrations in the api container (optional: app=sales)
	$(COMPOSE) exec api python manage.py makemigrations $(app)

migrate: ## Apply migrations in the api container (optional: app=sales)
	$(COMPOSE) exec api python manage.py migrate $(app)

seed: ## Load fictitious demo data (users, catalog and stock); safe to run again
	$(COMPOSE) exec api python manage.py seed_demo

test: ## Run the backend tests (optional: args="core/tests -k phone")
	$(COMPOSE) exec api pytest $(args)
