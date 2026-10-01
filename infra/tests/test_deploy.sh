#!/usr/bin/env bash
# Тесты оркестрации infra/deploy.sh: настоящего docker нет — compose подменён
# заглушкой, которая пишет вызовы в журнал. Проверяется то, что нельзя ломать:
# порядок шагов (миграция ДО пересоздания контейнеров), «упал шаг — следующие не
# выполняются», проверка .env и обновление кода только fast-forward.
#
# Запуск: bash infra/tests/test_deploy.sh
# SC2015: `A && B || C` ниже безопасен — pass/fail только печатают и не падают.
# shellcheck disable=SC2015
set -uo pipefail

# Windows (Git Bash): git и docker — нативные программы, им нужна автоконвертация
# msys-путей. При MSYS_NO_PATHCONV=1 (его нередко выставляют ради docker -v) git
# создаёт .git в корне диска C: (C:/tmp/...), а bash кладёт остальные файлы в настоящий /tmp —
# получаются два разных дерева, и сценарии падают с пустым выводом. На Linux
# переменная ни на что не влияет.
unset MSYS_NO_PATHCONV

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

PASS=0
FAIL=0
pass() { PASS=$((PASS + 1)); printf '  ok   %s\n' "$1"; }
fail() { FAIL=$((FAIL + 1)); printf '  FAIL %s\n' "$1"; }

git_quiet() { git -c user.email=t@t -c user.name=t -c commit.gpgsign=false "$@" >/dev/null 2>&1; }

# Свежий «сервер»: origin (bare) + клон с deploy.sh, прод-compose и валидным .env.
# Каждый сценарий — в своей новой директории: переиспользование одних и тех же путей
# после rm -rf на NTFS иногда ловило гонку с антивирусом/индексатором (разовые
# необъяснимые падения), а новая директория от неё свободна.
CASE_N=0
setup() {
  CASE_N=$((CASE_N + 1))
  CASE="$WORK/case$CASE_N"
  mkdir -p "$CASE"
  ORIGIN="$CASE/origin.git"; SRV="$CASE/srv"; DEV="$CASE/dev"
  CALLS_LOG="$CASE/calls.log"; OUT_LOG="$CASE/out.log"; ERR_LOG="$CASE/err.log"; STUB="$CASE/stub_compose.sh"
  git_quiet init --bare -b main "$ORIGIN"
  git_quiet clone "$ORIGIN" "$SRV"
  mkdir -p "$SRV/infra" "$SRV/compose"
  cp "$REPO_ROOT/infra/deploy.sh" "$SRV/infra/deploy.sh"
  cp "$REPO_ROOT/compose/docker-compose.prod.yml" "$SRV/compose/docker-compose.prod.yml"
  echo "version 1" > "$SRV/app.txt"
  git_quiet -C "$SRV" add -A
  git_quiet -C "$SRV" commit -m "initial"
  git_quiet -C "$SRV" push -u origin main
  cat > "$SRV/.env" <<'EOF'
POSTGRES_USER=platform
POSTGRES_PASSWORD=pgpass
POSTGRES_DB=platform
OPENAI_API_KEY=sk-test
JWT_SECRET=0123456789abcdef0123456789abcdef0123456789abcdef
PLATFORM_OWNER_EMAIL=owner@example.com
PLATFORM_OWNER_PASSWORD=a-long-enough-password
S3_ENDPOINT=https://fra1.digitaloceanspaces.com
S3_BUCKET=bucket
S3_ACCESS_KEY=key
S3_SECRET_KEY=secret
SITE_ADDRESS=203-0-113-10.sslip.io
ACME_EMAIL=ops@example.com
EOF
  # Заглушка compose: пишет аргументы, падает, если вызов содержит $STUB_FAIL_ON.
  cat > "$STUB" <<EOF
#!/usr/bin/env bash
echo "\$*" >> "$CALLS_LOG"
if [ -n "\${STUB_FAIL_ON:-}" ] && [[ "\$*" == *"\$STUB_FAIL_ON"* ]]; then exit 1; fi
exit 0
EOF
  chmod +x "$STUB"
}

# Запуск deploy.sh в окружении теста; вывод в $OUT_LOG
run_deploy() {
  (
    cd "$SRV" || exit 99
    # TEST_SMOKE=1 включает проверку HTTPS; STUB_BIN — каталог с заглушками curl/sleep
    [ -n "${STUB_BIN:-}" ] && export PATH="$STUB_BIN:$PATH"
    COMPOSE_BIN="$STUB" SKIP_SMOKE="$([ "${TEST_SMOKE:-0}" = "1" ] && echo 0 || echo 1)" SKIP_PRUNE=1 \
      bash infra/deploy.sh > "$OUT_LOG" 2>&1
  )
}

calls() { cat "$CALLS_LOG" 2>/dev/null || true; }
line_of() { calls | grep -n -- "$1" | head -1 | cut -d: -f1; }
has_call() { calls | grep -q -- "$1"; }

echo "deploy.sh"

# 1. Счастливый путь: build → проверка хранилища → миграция → up, строго в этом порядке.
setup
if run_deploy; then
  b="$(line_of '^build')"; s="$(line_of '_deploy-check')"; m="$(line_of 'alembic upgrade head')"; u="$(line_of '^up ')"
  if [ -n "$b" ] && [ -n "$s" ] && [ -n "$m" ] && [ -n "$u" ] && [ "$b" -lt "$s" ] && [ "$s" -lt "$m" ] && [ "$m" -lt "$u" ]; then
    pass "порядок: сборка → проверка хранилища → миграция → запуск"
  else
    fail "порядок шагов нарушен (build=$b storage=$s migrate=$m up=$u)"
  fi
  has_call '^up -d --remove-orphans --wait' && pass "up с --wait (ждёт healthy)" || fail "up без --wait"
else
  fail "счастливый путь завершился ошибкой: $(tail -3 "$OUT_LOG")"
fi

# 2. Миграция упала — контейнеры НЕ пересоздаются (главное свойство скрипта).
setup
if STUB_FAIL_ON="alembic" run_deploy; then
  fail "миграция упала, а деплой сообщил об успехе"
else
  has_call '^up ' && fail "после упавшей миграции вызван up" || pass "миграция упала → up не вызывался"
  grep -q "НЕ пересозданы" "$OUT_LOG" && pass "сообщение объясняет, что стенд остался на прежней версии" || fail "нет внятного сообщения о миграции"
fi

# 3. Хранилище недоступно — до миграции и до up не доходим.
setup
if STUB_FAIL_ON="_deploy-check" run_deploy; then
  fail "хранилище недоступно, а деплой сообщил об успехе"
else
  has_call 'alembic' && fail "миграция запущена при недоступном хранилище" || pass "хранилище недоступно → миграция и up не запускались"
  grep -q "S3_ENDPOINT" "$OUT_LOG" && pass "сообщение называет, что проверить в .env" || fail "нет подсказки про S3_* в .env"
fi

# 4. SKIP_S3_CHECK пропускает проверку.
setup
SKIP_S3_CHECK=1 run_deploy && ! has_call '_deploy-check' && pass "SKIP_S3_CHECK=1 пропускает проверку хранилища" || fail "SKIP_S3_CHECK не сработал"

# 5. Не хватает переменных в .env — стоп ДО сборки, и все пропуски названы разом.
setup
sed -i '/^S3_BUCKET=/d;/^OPENAI_API_KEY=/d' "$SRV/.env"
if run_deploy; then
  fail "пустой .env принят"
else
  [ -z "$(calls)" ] && pass "неполный .env → compose не вызывался" || fail "compose вызван при неполном .env"
  grep -q "S3_BUCKET" "$OUT_LOG" && grep -q "OPENAI_API_KEY" "$OUT_LOG" && pass "названы все пропущенные переменные сразу" || fail "названы не все пропуски: $(grep ОШИБКА "$OUT_LOG")"
fi

# 6. Переменная есть, но значение пустое — тоже пропуск.
setup
sed -i 's/^S3_SECRET_KEY=.*/S3_SECRET_KEY=/' "$SRV/.env"
run_deploy && fail "пустое значение принято" || { grep -q "S3_SECRET_KEY" "$OUT_LOG" && pass "пустое значение считается пропуском" || fail "пустое значение не замечено"; }

# 7. Слабый JWT_SECRET.
setup
sed -i 's/^JWT_SECRET=.*/JWT_SECRET=short/' "$SRV/.env"
run_deploy && fail "короткий JWT_SECRET принят" || { [ -z "$(calls)" ] && pass "короткий JWT_SECRET отклонён до сборки" || fail "сборка запущена с коротким JWT_SECRET"; }

# 7b. Репозиторий публичный — значения из dev-compose знает любой. По известному
# JWT_SECRET токены сессий подделываются, поэтому в прод они не должны попасть.
for pair in \
  "JWT_SECRET=dev-insecure-jwt-secret-do-not-use-in-prod" \
  "PLATFORM_OWNER_PASSWORD=devpassword123" \
  "POSTGRES_PASSWORD=platform"; do
  var="${pair%%=*}"
  setup
  sed -i "s|^${var}=.*|${pair}|" "$SRV/.env"
  if run_deploy; then
    fail "$var из публичного dev-compose принят"
  else
    if [ -z "$(calls)" ] && grep -q "$var" "$OUT_LOG"; then
      pass "$var из публичного dev-compose отклонён до сборки"
    else
      fail "$var из dev-compose отклонён не так: calls='$(calls)' out='$(grep ОШИБКА "$OUT_LOG")'"
    fi
  fi
done

# 7c. Список «известных публичных значений» в deploy.sh не разошёлся с dev-compose:
# сменят dev-пароль — тест напомнит поправить список (иначе защита молча протухнет).
for var in JWT_SECRET PLATFORM_OWNER_PASSWORD POSTGRES_PASSWORD; do
  val="$(awk -v k="${var}:" '$1 == k {print $2; exit}' "$REPO_ROOT/compose/docker-compose.dev.yml")"
  if [ -n "$val" ] && grep -qF "\"${var}=${val}\"" "$REPO_ROOT/infra/deploy.sh"; then
    pass "deploy.sh знает dev-значение $var"
  else
    fail "dev-значение $var ('$val') отсутствует в списке deploy.sh"
  fi
done

# 8. SITE_ADDRESS со схемой / localhost.
setup
sed -i 's|^SITE_ADDRESS=.*|SITE_ADDRESS=https://example.com/|' "$SRV/.env"
run_deploy && fail "SITE_ADDRESS со схемой принят" || pass "SITE_ADDRESS со схемой и путём отклонён"
setup
sed -i 's|^SITE_ADDRESS=.*|SITE_ADDRESS=localhost|' "$SRV/.env"
run_deploy && fail "SITE_ADDRESS=localhost принят" || pass "SITE_ADDRESS=localhost отклонён"

# 9. Значения в кавычках и CRLF (.env мог побывать на Windows) читаются верно.
setup
sed -i 's/^S3_BUCKET=.*/S3_BUCKET="bucket"/' "$SRV/.env"
sed -i 's/$/\r/' "$SRV/.env"
run_deploy && pass "кавычки и CRLF в .env не мешают" || fail "кавычки/CRLF сломали разбор: $(grep ОШИБКА "$OUT_LOG")"

# 10. Новый коммит в origin подтягивается fast-forward-ом.
setup
git_quiet clone "$ORIGIN" "$DEV"
echo "version 2" > "$DEV/app.txt"
git_quiet -C "$DEV" commit -am "second"
git_quiet -C "$DEV" push origin main
run_deploy && [ "$(cat "$SRV/app.txt")" = "version 2" ] && pass "новый коммит из origin выложен" || fail "код не обновился"

# 11. Локальные правки на сервере конфликтуют с обновлением — стоп до сборки.
setup
git_quiet clone "$ORIGIN" "$DEV"
echo "version 2" > "$DEV/app.txt"
git_quiet -C "$DEV" commit -am "second"
git_quiet -C "$DEV" push origin main
echo "hotfix on server" > "$SRV/app.txt"
if run_deploy; then
  fail "правка на сервере затёрта обновлением"
else
  has_call '^build' && fail "сборка запущена при конфликте кода" || pass "конфликт с локальной правкой → стоп до сборки"
  [ "$(cat "$SRV/app.txt")" = "hotfix on server" ] && pass "локальная правка сохранена" || fail "локальная правка потеряна"
fi

# 11b. На сервере есть свой коммит, в origin — другой (ветки разошлись): без --ff-only
# git молча сделал бы merge-коммит и выложил непонятную смесь. Должен быть стоп.
setup
git_quiet clone "$ORIGIN" "$DEV"
echo "from origin" > "$DEV/origin_only.txt"
git_quiet -C "$DEV" add -A
git_quiet -C "$DEV" commit -m "origin side"
git_quiet -C "$DEV" push origin main
echo "from server" > "$SRV/server_only.txt"
git_quiet -C "$SRV" add -A
git_quiet -C "$SRV" commit -m "server side"
head_before="$(git -C "$SRV" rev-parse HEAD)"
if run_deploy; then
  fail "ветки разошлись, а деплой прошёл"
else
  has_call '^build' && fail "сборка запущена при разошедшихся ветках" || pass "разошедшиеся ветки → стоп до сборки"
  [ "$(git -C "$SRV" rev-parse HEAD)" = "$head_before" ] && pass "merge-коммит не создан" || fail "на сервере появился merge-коммит"
fi

# 12. SKIP_PULL=1 не обращается к git (работает и без доступа к origin).
setup
rm -rf "$ORIGIN"
SKIP_PULL=1 run_deploy && pass "SKIP_PULL=1 работает без доступа к origin" || fail "SKIP_PULL=1 полез в git: $(tail -2 "$OUT_LOG")"

# 12b. Проверка HTTPS после выкладки. curl и sleep подменены заглушками: тест не ходит в
# сеть и не ждёт 90 секунд.
make_stub_bin() { # $1 — код возврата curl
  STUB_BIN="$CASE/stubbin"
  mkdir -p "$STUB_BIN"
  printf '#!/bin/sh\nexit %s\n' "$1" > "$STUB_BIN/curl"
  printf '#!/bin/sh\nexit 0\n' > "$STUB_BIN/sleep"
  chmod +x "$STUB_BIN/curl" "$STUB_BIN/sleep"
}

setup
make_stub_bin 0
if TEST_SMOKE=1 STUB_BIN="$STUB_BIN" run_deploy; then
  pass "https отвечает → деплой завершается успешно"
else
  fail "https отвечает, а деплой упал: $(tail -3 "$OUT_LOG")"
fi

setup
make_stub_bin 22
if TEST_SMOKE=1 STUB_BIN="$STUB_BIN" run_deploy; then
  fail "https не отвечает, а деплой сообщил об успехе"
else
  grep -q "https://203-0-113-10.sslip.io/login не отвечает" "$OUT_LOG" && pass "https не отвечает → ошибка называет адрес" \
    || fail "ошибка не называет адрес: $(grep ОШИБКА "$OUT_LOG")"
  # Общая квота Let's Encrypt на sslip.io — реальная причина отказа; подсказка должна
  # вести к nip.io (у неё отдельная квота) и в логи caddy.
  grep -q "nip.io" "$OUT_LOG" && grep -q "logs caddy" "$OUT_LOG" && pass "подсказка про квоту sslip.io → nip.io и логи caddy" \
    || fail "нет подсказки про квоту sslip.io: $(grep -c . "$OUT_LOG") строк вывода"
  grep -q "Откат:" "$OUT_LOG" && fail "после отказа https напечатан успешный итог" || pass "успешный итог не печатается при отказе https"
fi

# 13. Журнал выкладок и подсказка отката.
setup
run_deploy
[ -s "$SRV/deploy.log" ] && pass "deploy.log записан" || fail "deploy.log не создан"
grep -q "Откат:" "$OUT_LOG" && pass "печатается команда отката" || fail "нет команды отката"

echo
echo "compose.sh"

# 14. Обёртка читает .env из КОРНЯ репозитория (голый compose искал бы compose/.env).
if command -v docker >/dev/null 2>&1; then
  setup
  cp "$REPO_ROOT/infra/compose.sh" "$SRV/infra/compose.sh"
  if (cd "$WORK" && bash "$SRV/infra/compose.sh" config -q >/dev/null 2>"$ERR_LOG"); then
    pass "compose.sh находит .env в корне репозитория (из любой текущей директории)"
  else
    fail "compose.sh не подхватил .env: $(head -2 "$ERR_LOG")"
  fi
  # Контрольный: тот же вызов БЕЗ обёртки падает — иначе тест выше ничего не доказывает.
  if (cd "$SRV" && docker compose -f compose/docker-compose.prod.yml config -q >/dev/null 2>&1); then
    fail "голый compose тоже нашёл .env — тест не доказывает необходимость обёртки"
  else
    pass "без обёртки тот же compose падает (контроль)"
  fi
  rm "$SRV/.env"
  if (cd "$WORK" && bash "$SRV/infra/compose.sh" config -q >/dev/null 2>"$ERR_LOG"); then
    fail "compose.sh молча отработал без .env"
  else
    grep -q ".env не найден" "$ERR_LOG" && pass "без .env — внятная ошибка" || fail "нет внятной ошибки без .env: $(head -2 "$ERR_LOG")"
  fi
else
  echo "  skip docker не найден — тесты compose.sh пропущены"
fi

echo
echo "итого: $PASS ok, $FAIL FAIL"
[ "$FAIL" -eq 0 ]
