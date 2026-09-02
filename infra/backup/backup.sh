#!/usr/bin/env bash
# Ночной pg_dump прод-БД в файл + ротация старых бэкапов.
# STAGE1_CORE Блок 3, п.3: "крон pg_dump в файл — обязателен".
# Строка для crontab на сервере — см. docs/RUNBOOK.md.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Секреты — только из .env на сервере (ADR-007), в скрипте не хардкодим.
if [ -f "${REPO_ROOT}/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "${REPO_ROOT}/.env"
  set +a
fi

COMPOSE_PROJECT="${COMPOSE_PROJECT:-platform-prod}"
CONTAINER="${COMPOSE_PROJECT}-postgres-1"
BACKUP_DIR="${BACKUP_DIR:-${REPO_ROOT}/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
: "${POSTGRES_USER:?POSTGRES_USER не задан — нет .env рядом со скриптом или переменной в окружении}"
: "${POSTGRES_DB:?POSTGRES_DB не задан}"

mkdir -p "$BACKUP_DIR"
timestamp="$(date +%Y%m%d_%H%M%S)"
out_file="${BACKUP_DIR}/${POSTGRES_DB}_${timestamp}.sql.gz"

docker exec "$CONTAINER" pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$out_file"
echo "backup written to ${out_file}"

# Ротация: не храним бэкапы старше RETENTION_DAYS дней.
find "$BACKUP_DIR" -name "*.sql.gz" -mtime "+${RETENTION_DAYS}" -delete
