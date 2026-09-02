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
	pip install -e libs/core -e libs/db -e services/worker -r requirements-dev.txt
	cd services/gateway && npm install

test:
	. .venv/Scripts/activate 2>/dev/null || . .venv/bin/activate; pytest
	cd services/gateway && npm test

lint:
	. .venv/Scripts/activate 2>/dev/null || . .venv/bin/activate; \
	ruff check . && mypy libs/core/src libs/db/src services/worker/src
	cd services/gateway && npm run lint

migrate:
	. .venv/Scripts/activate 2>/dev/null || . .venv/bin/activate; \
	alembic -c libs/db/alembic.ini upgrade head
