#!/usr/bin/env bash
# Деплой и обновление прод-стенда. Запускается НА СЕРВЕРЕ, из любой директории:
#   /root/whatsapp-bot/infra/deploy.sh
#
# Порядок критичен (docs/RUNBOOK.md «Обновление стенда»): миграция — ДО того, как
# новый код начнёт ею пользоваться. Обратный порядок даёт тихие сбои: новый код
# падает на "relation does not exist", исключение глотает общий except в пайплайне,
# и клиент просто не получает ответа. Поэтому: проверки → код → сборка → проверка
# хранилища → миграция на новом образе → пересоздание контейнеров → проверка HTTPS.
# Любой шаг упал — следующие не выполняются, старые контейнеры остаются работать.
#
# Переменные окружения (все необязательные):
#   DEPLOY_BRANCH   ветка для выкладки (по умолчанию main)
#   SKIP_PULL=1     не трогать git — выложить то, что уже лежит (откат: git checkout <коммит>)
#   SKIP_S3_CHECK=1 пропустить проверку записи в хранилище
#   SKIP_SMOKE=1    пропустить проверку https://$SITE_ADDRESS/login
#   SKIP_PRUNE=1    не чистить неиспользуемые образы после выкладки
#   COMPOSE_BIN     чем звать compose (для тестов; по умолчанию infra/compose.sh)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_BIN="${COMPOSE_BIN:-$ROOT/infra/compose.sh}"
BRANCH="${DEPLOY_BRANCH:-main}"

log() { printf '\n==> %s\n' "$*"; }
die() { printf '\nОШИБКА: %s\n' "$*" >&2; exit 1; }

cd "$ROOT"

[ -f .env ] || die ".env не найден в $ROOT — создайте его по .env.example (docs/RUNBOOK.md)"

# Значение переменной из .env: без кавычек, краевых пробелов и \r (файл мог
# побывать на Windows).
env_value() {
  local line
  line="$(grep -E "^$1=" .env | tail -1 || true)"
  line="${line#*=}"
  line="${line%$'\r'}"
  line="${line#"${line%%[![:space:]]*}"}"
  line="${line%"${line##*[![:space:]]}"}"
  line="${line#\"}"; line="${line%\"}"
  line="${line#\'}"; line="${line%\'}"
  printf '%s' "$line"
}

# --- 1. Проверка .env: все пропуски разом, а не по одному за запуск ----------------
log "Проверка .env"
# Список обязательных берём из самого compose-файла (${VAR:?...}), чтобы не вести
# его в двух местах.
missing=()
while read -r var; do
  [ -n "$var" ] || continue
  [ -n "$(env_value "$var")" ] || missing+=("$var")
done < <(grep -oE '\$\{[A-Z_0-9]+:\?' compose/docker-compose.prod.yml | sed -E 's/^\$\{//; s/:\?$//' | sort -u)
if [ "${#missing[@]}" -gt 0 ]; then
  die "в .env не заданы: ${missing[*]}"
fi

site="$(env_value SITE_ADDRESS)"
[[ "$site" =~ ^[A-Za-z0-9.-]+$ ]] || die "SITE_ADDRESS должен быть именем хоста без https:// и пути (сейчас: '$site')"
[ "$site" != "localhost" ] || die "SITE_ADDRESS=localhost годится только для проверки на своей машине, а не для сервера"
[ "${#site}" -ge 4 ] || die "SITE_ADDRESS слишком короткий: '$site'"

# На ACME_EMAIL Caddy регистрируется у Let's Encrypt и ZeroSSL (запасной центр). Они отклоняют
# адрес не похожий на почту и адреса на зарезервированных доменах — без этой проверки
# об опечатке узнаешь только в конце долгой сборки, когда сертификат так и не выдастся.
acme="$(env_value ACME_EMAIL)"
[[ "$acme" =~ ^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$ ]] || die "ACME_EMAIL не похож на адрес электронной почты: '$acme'"
case "${acme##*@}" in
  example.com | example.net | example.org | *.example.com | *.example.net | *.example.org | *.test | *.invalid | *.local | *.localhost)
    die "ACME_EMAIL на зарезервированном домене (${acme##*@}) — Let's Encrypt такие адреса отклоняет, сертификат не выдастся. Укажите настоящий ящик." ;;
esac

[ "$(env_value JWT_SECRET | wc -c)" -ge 32 ] || die "JWT_SECRET короче 32 символов — сгенерируйте: openssl rand -hex 32"
[ "$(env_value PLATFORM_OWNER_PASSWORD | wc -c)" -ge 12 ] \
  || printf 'ПРЕДУПРЕЖДЕНИЕ: PLATFORM_OWNER_PASSWORD короче 12 символов — это пароль владельца платформы\n' >&2

# Репозиторий публичный: значения из compose/docker-compose.dev.yml знает любой.
# Проверка длины их пропускает (dev-JWT_SECRET длиннее 32 символов), а в проде это
# открытая дверь — по известному JWT_SECRET токены сессий подделываются.
# Список обязан совпадать с dev-compose — это проверяет infra/tests/test_deploy.sh.
known_public_dev_values=(
  "JWT_SECRET=dev-insecure-jwt-secret-do-not-use-in-prod"
  "PLATFORM_OWNER_PASSWORD=devpassword123"
  "POSTGRES_PASSWORD=platform"
)
for pair in "${known_public_dev_values[@]}"; do
  var="${pair%%=*}"
  if [ "$(env_value "$var")" = "${pair#*=}" ]; then
    die "$var в .env равен значению из публичного dev-compose — задайте свой (например: openssl rand -hex 24)"
  fi
done

# --- 2. Код -----------------------------------------------------------------------
previous="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
if [ "${SKIP_PULL:-0}" = "1" ]; then
  log "Код: git пропущен (SKIP_PULL=1), выкладываем $previous"
else
  log "Код: обновление до origin/$BRANCH"
  git fetch --quiet origin "$BRANCH"
  git checkout --quiet "$BRANCH"
  # --ff-only: расхождение или правки на сервере — стоп, а не тихий merge-коммит
  git merge --quiet --ff-only "origin/$BRANCH"
fi
current="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
git log -1 --oneline 2>/dev/null || true

# --- 3. Сборка (старые контейнеры не трогаем) ---------------------------------------
log "Сборка образов"
"$COMPOSE_BIN" build

# --- 4. Хранилище: ключ/endpoint/бакет проверяем сейчас, а не при первой загрузке фото
if [ "${SKIP_S3_CHECK:-0}" = "1" ]; then
  log "Проверка хранилища пропущена (SKIP_S3_CHECK=1)"
else
  log "Проверка хранилища (запись и чтение тестового объекта)"
  "$COMPOSE_BIN" run --rm --no-deps api python -c "
import asyncio
from integrations.storage import create_storage

async def main() -> None:
    storage = create_storage()
    key = '_deploy-check/ping.txt'
    await storage.put(key, b'ok', 'text/plain')
    if await storage.get(key) != b'ok':
        raise SystemExit('хранилище: прочитанное не совпало с записанным')
    print('хранилище ок')

asyncio.run(main())
" || die "хранилище недоступно: проверьте S3_ENDPOINT, S3_BUCKET (бакет должен существовать), S3_REGION и ключи в .env"
fi

# --- 5. Миграция на НОВОМ образе: старые worker/api/celery пока работают -------------
# Безопасно, потому что миграции проекта только additive (новая таблица или
# nullable-колонка): старый код про них не знает и работает как раньше.
log "Миграция БД"
"$COMPOSE_BIN" run --rm worker sh -c "cd /app/libs/db && python -m alembic upgrade head" \
  || die "миграция не прошла — контейнеры НЕ пересозданы, стенд работает на прежней версии"

# --- 6. Пересоздание контейнеров, ждём healthy ---------------------------------------
log "Запуск контейнеров"
if ! "$COMPOSE_BIN" up -d --remove-orphans --wait --wait-timeout 300; then
  "$COMPOSE_BIN" ps || true
  die "не все сервисы стали healthy за 5 минут — смотрите: ./infra/compose.sh logs <сервис> --tail=100"
fi

# --- 7. Проверка снаружи ---------------------------------------------------------------
if [ "${SKIP_SMOKE:-0}" = "1" ]; then
  log "Проверка HTTPS пропущена (SKIP_SMOKE=1)"
else
  log "Проверка https://$site/login (при первом запуске Caddy выпускает сертификат — до 90 с)"
  ok=0
  for _ in $(seq 1 30); do
    if curl -fsS -o /dev/null --max-time 5 "https://$site/login" 2>/dev/null; then ok=1; break; fi
    sleep 3
  done
  [ "$ok" = "1" ] || die "стек поднят, но https://$site/login не отвечает.
Частые причины:
  1. закрыт порт 80 или 443 (файрвол сервера и Cloud Firewall DigitalOcean);
  2. SITE_ADDRESS не совпадает с IP сервера;
  3. для sslip.io исчерпана ОБЩАЯ недельная квота Let's Encrypt (её делят все пользователи
     сервиса) — в логах caddy будет 'rate limit'. Замените в .env зону на nip.io
     (203-0-113-10.nip.io — у неё отдельная квота) и запустите deploy.sh ещё раз.
Подробности: ./infra/compose.sh logs caddy"
fi

# --- 8. Итог ------------------------------------------------------------------------------
if [ "${SKIP_PRUNE:-0}" != "1" ]; then
  docker image prune -f >/dev/null 2>&1 || true  # только «висячие» образы прошлых сборок
fi
echo "$(date -Is 2>/dev/null || date) $current" >> "$ROOT/deploy.log" || true

log "Готово: $current (было: $previous)"
"$COMPOSE_BIN" ps
echo
echo "Кабинет:  https://$site/"
echo "Откат:    git checkout $previous && SKIP_PULL=1 $0"
