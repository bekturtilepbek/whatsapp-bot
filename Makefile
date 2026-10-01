COMPOSE = docker compose -f compose/docker-compose.dev.yml

.PHONY: dev dev-down test test-infra lint migrate install

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

# Тесты infra/deploy.sh и infra/compose.sh: compose подменён заглушкой, настоящий деплой не нужен
test-infra:
	bash infra/tests/test_deploy.sh

lint:
	. .venv/Scripts/activate 2>/dev/null || . .venv/bin/activate; \
	ruff check . && mypy libs/core/src libs/db/src libs/integrations/src libs/scheduling/src libs/tools/src services/worker/src services/celery/src services/api/src
	cd services/gateway && npm run lint
	cd services/admin-web && npm run lint

migrate:
	. .venv/Scripts/activate 2>/dev/null || . .venv/bin/activate; \
	alembic -c libs/db/alembic.ini upgrade head
