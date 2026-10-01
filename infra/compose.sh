#!/usr/bin/env bash
# docker compose для прод-стека — все команды RUNBOOK идут через эту обёртку.
#
# Нужна потому, что compose ищет .env рядом с compose-файлом (compose/.env), а не
# в корне репозитория, где его ждут backup.sh и RUNBOOK: без --env-file любая
# команда падала бы на "required variable ... is missing a value".
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ ! -f "$ROOT/.env" ]; then
  echo "ОШИБКА: $ROOT/.env не найден — создайте его по .env.example (docs/RUNBOOK.md)" >&2
  exit 1
fi

exec docker compose --env-file "$ROOT/.env" -f "$ROOT/compose/docker-compose.prod.yml" "$@"
