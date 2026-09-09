COMPOSE = docker compose -f compose/docker-compose.dev.yml

.PHONY: dev dev-down test lint migrate install

# Локальный стек: postgres, redis, gateway, worker
dev:
	$(COMPOSE) up --build

dev-down:
	$(COMPOSE) down

# Python-окружение для локальных тестов и линта (venv в .venv)
install:
	python -m venv .venv || true
	. .venv/Scripts/activate 2>/dev/null || . .venv/bin/activate; \
	pip install -e libs/core -e libs/db -e libs/llm -e libs/integrations -e libs/scheduling -e libs/tools -e services/worker -e services/celery -e services/api -r requirements-dev.txt
	cd services/gateway && npm install
	cd services/admin-web && npm install

test:
	. .venv/Scripts/activate 2>/dev/null || . .venv/bin/activate; pytest
	cd services/gateway && npm test
	cd services/admin-web && npm test

lint:
	. .venv/Scripts/activate 2>/dev/null || . .venv/bin/activate; \
	ruff check . && mypy libs/core/src libs/db/src libs/integrations/src libs/scheduling/src libs/tools/src services/worker/src services/celery/src
	cd services/gateway && npm run lint
	cd services/admin-web && npm run lint

migrate:
	. .venv/Scripts/activate 2>/dev/null || . .venv/bin/activate; \
	alembic -c libs/db/alembic.ini upgrade head
