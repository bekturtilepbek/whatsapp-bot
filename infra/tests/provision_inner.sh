#!/usr/bin/env bash
# Выполняется ВНУТРИ контейнера ubuntu:24.04 (запускается из test_provision.sh, сам по
# себе на машине разработчика не нужен). Проверяет ту часть provision.sh, которую можно
# проверить без настоящего сервера: когда нужен deploy-ключ, как берутся ключи хоста
# GitHub, клонирование и повторные запуски. Docker/swap/файрвол пропускаются
# (PROVISION_SKIP_SYSTEM=1) — они меняют ядро хоста.
# SC2015: `A && B || C` ниже безопасен — pass/fail только печатают и не падают.
# shellcheck disable=SC2015
set -uo pipefail

PROV=/infra/provision.sh
PASS=0
FAIL=0
pass() { PASS=$((PASS + 1)); printf '  ok   %s\n' "$1"; }
fail() { FAIL=$((FAIL + 1)); printf '  FAIL %s\n' "$1"; }

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq >/dev/null 2>&1
apt-get install -y -qq git openssh-client curl python3 ca-certificates psmisc >/dev/null 2>&1 \
  || { echo "  FAIL не удалось поставить зависимости теста"; exit 1; }

git config --global user.email t@t
git config --global user.name t
git config --global init.defaultBranch main

# «GitHub»: bare-репозиторий с веткой main
git init -q --bare /tmp/origin.git
git clone -q /tmp/origin.git /tmp/seed 2>/dev/null
(cd /tmp/seed && echo hi > f && git add f && git commit -qm init && git push -q origin main)

# Ответ API GitHub в том же формате (ключи нарочно фиктивные — проверяется только разбор)
cat > /tmp/meta.json <<'EOF'
{"hooks":["192.30.252.0/22"],"ssh_keys":["ssh-ed25519 AAAAFAKEKEYONE","ecdsa-sha2-nistp256 AAAAFAKEKEYTWO","ssh-rsa AAAAFAKEKEYTHREE"]}
EOF

# Свежий HOME на каждый сценарий: ключи и known_hosts не текут между ними
new_home() { H="$(mktemp -d)"; export HOME="$H"; }
# prov <env-пары...> — запуск provision.sh; код возврата в $RC, вывод в $H/out.log
prov() {
  env PROVISION_SKIP_SYSTEM=1 "$@" bash "$PROV" > "$H/out.log" 2>&1
  RC=$?
}
out_has() { grep -q -- "$1" "$H/out.log"; }

echo "provision.sh"

# 1. Публичный репозиторий (не SSH-адрес): клонируется, deploy-ключ НЕ создаётся.
new_home
prov REPO_URL=file:///tmp/origin.git INSTALL_DIR=/tmp/srv1
[ "$RC" -eq 0 ] && [ -f /tmp/srv1/f ] && pass "публичный адрес: репозиторий склонирован с первого раза" \
  || fail "публичный адрес не склонировался (rc=$RC): $(tail -3 "$H/out.log")"
[ ! -e "$H/.ssh/platform_deploy" ] && pass "публичный адрес: deploy-ключ не создаётся" \
  || fail "для публичного адреса создан ненужный deploy-ключ"
out_has "Сервер готов" && pass "в конце печатаются следующие шаги" || fail "нет подсказки про следующие шаги"

# 2. Повторный запуск — готовый клон не трогается.
prov REPO_URL=file:///tmp/origin.git INSTALL_DIR=/tmp/srv1
[ "$RC" -eq 0 ] && out_has "уже склонирован" && pass "повторный запуск идемпотентен" \
  || fail "повторный запуск: rc=$RC, $(tail -3 "$H/out.log")"

# 3. Клон уже сделан руками (git clone, как привык делать пользователь), REPO_URL не задан.
new_home
git clone -q /tmp/origin.git /tmp/srv_manual
prov INSTALL_DIR=/tmp/srv_manual
[ "$RC" -eq 0 ] && out_has "уже склонирован" && [ ! -e "$H/.ssh/platform_deploy" ] \
  && pass "ручной git clone + запуск скрипта без REPO_URL работает, ключи не нужны" \
  || fail "ручной клон: rc=$RC, $(tail -3 "$H/out.log")"

# 4. Нет ни клона, ни REPO_URL — подсказка и код 0, ничего не создаётся.
new_home
prov INSTALL_DIR=/tmp/srv_none
[ "$RC" -eq 0 ] && out_has "REPO_URL не задан" && [ ! -d /tmp/srv_none ] && [ ! -e "$H/.ssh/platform_deploy" ] \
  && pass "без REPO_URL и клона: подсказка, ничего не создано" \
  || fail "без REPO_URL: rc=$RC, $(tail -3 "$H/out.log")"

# 5. Несуществующая ветка в публичном репозитории — внятная ошибка, ключ не создаётся.
new_home
prov REPO_URL=file:///tmp/origin.git INSTALL_DIR=/tmp/srv5 DEPLOY_BRANCH=nope
[ "$RC" -ne 0 ] && out_has "nope" && [ ! -e "$H/.ssh/platform_deploy" ] \
  && pass "несуществующая ветка: ошибка называет ветку" \
  || fail "несуществующая ветка: rc=$RC, $(tail -3 "$H/out.log")"

# 6. SSH-адрес (приватный репозиторий): ключ создаётся, ключи хоста берутся из API,
#    клонирование не удаётся (ключ ещё не добавлен) и скрипт печатает публичный ключ.
new_home
prov REPO_URL=git@localhost:x/y.git INSTALL_DIR=/tmp/srv6 GITHUB_META_URL=file:///tmp/meta.json
pub="$(cat "$H/.ssh/platform_deploy.pub" 2>/dev/null || true)"
[ -n "$pub" ] && [ "$(stat -c %a "$H/.ssh/platform_deploy")" = "600" ] \
  && pass "SSH-адрес: deploy-ключ создан (права 600)" || fail "SSH-адрес: ключ не создан или права не 600"
[ "$(grep -c '^github.com ' "$H/.ssh/known_hosts")" -eq 3 ] \
  && grep -q "github.com ssh-ed25519 AAAAFAKEKEYONE" "$H/.ssh/known_hosts" \
  && pass "ключи хоста GitHub взяты из API (все три)" || fail "known_hosts неверный: $(cat "$H/.ssh/known_hosts")"
[ "$(grep -c "IdentityFile $H/.ssh/platform_deploy" "$H/.ssh/config")" -eq 1 ] \
  && pass "ssh config указывает на deploy-ключ" || fail "ssh config неверный"
[ "$RC" -ne 0 ] && out_has "Deploy keys" && out_has "$(printf '%s' "$pub" | awk '{print $2}')" \
  && pass "клон не удался → напечатан публичный ключ и инструкция" \
  || fail "после неудачного клона нет ключа/инструкции (rc=$RC): $(tail -5 "$H/out.log")"
[ ! -d /tmp/srv6 ] && pass "неудачный клон не оставил каталог" || fail "остался каталог после неудачного клона"

# 7. Повторный запуск того же: ключ тот же, записи не дублируются.
before="$(ssh-keygen -lf "$H/.ssh/platform_deploy.pub")"
prov REPO_URL=git@localhost:x/y.git INSTALL_DIR=/tmp/srv6 GITHUB_META_URL=file:///tmp/meta.json
after="$(ssh-keygen -lf "$H/.ssh/platform_deploy.pub")"
[ "$before" = "$after" ] && pass "повторный запуск не пересоздаёт ключ" || fail "ключ пересоздан — прежний, добавленный в GitHub, перестал бы работать"
[ "$(grep -c '^github.com ' "$H/.ssh/known_hosts")" -eq 3 ] && [ "$(grep -c 'IdentityFile' "$H/.ssh/config")" -eq 1 ] \
  && pass "known_hosts и ssh config не дублируются" || fail "записи продублировались"

# 8. Ключи GitHub не получить НИ из API, НИ через ssh-keyscan — внятная ошибка,
#    а не молчаливое падение. (ssh-keyscan подменён заглушкой, чтобы тест не зависел от сети.)
new_home
mkdir -p /tmp/stubbin
printf '#!/bin/sh\nexit 1\n' > /tmp/stubbin/ssh-keyscan && chmod +x /tmp/stubbin/ssh-keyscan
prov PATH="/tmp/stubbin:$PATH" REPO_URL=git@localhost:x/y.git INSTALL_DIR=/tmp/srv8 GITHUB_META_URL=file:///nonexistent
[ "$RC" -ne 0 ] && out_has "ключи хоста GitHub" \
  && pass "нет ключей хоста GitHub → внятная ошибка про сеть" \
  || fail "нет ключей хоста GitHub: rc=$RC, вывод: $(tail -4 "$H/out.log")"

# 9. API недоступен, но ssh-keyscan отработал — предупреждение и запасной путь.
new_home
printf '#!/bin/sh\necho "github.com ssh-ed25519 AAAAFAKEFROMKEYSCAN"\n' > /tmp/stubbin/ssh-keyscan
prov PATH="/tmp/stubbin:$PATH" REPO_URL=git@localhost:x/y.git INSTALL_DIR=/tmp/srv9 GITHUB_META_URL=file:///nonexistent
out_has "ПРЕДУПРЕЖДЕНИЕ" && grep -q "AAAAFAKEFROMKEYSCAN" "$H/.ssh/known_hosts" \
  && pass "API недоступен → предупреждение и запасной ssh-keyscan" \
  || fail "запасной путь не сработал: $(tail -4 "$H/out.log")"

# 10. apt занят (cloud-init и unattended-upgrades на свежем droplet в первые минуты держат
#     блокировки): provision.sh должен ждать освобождения, а не падать с "Could not get lock".
#     Функция вынимается из скрипта как есть; die в тесте завершает только подоболочку.
eval "$(sed -n '/^wait_for_apt() {/,/^}/p' "$PROV")"
die() { echo "DIE: $*" >&2; exit 1; }
touch /var/lib/dpkg/lock-frontend

if ! declare -F wait_for_apt >/dev/null; then
  fail "wait_for_apt не найдена в provision.sh"
else
  # 10a. Блокировки нет — возврат сразу, без ожидания.
  start=$SECONDS
  ( wait_for_apt ) > /tmp/wait_a.log 2>&1; rc=$?
  [ "$rc" -eq 0 ] && [ $((SECONDS - start)) -le 2 ] && pass "apt свободен → без ожидания" \
    || fail "apt свободен, а ожидание rc=$rc, $((SECONDS - start)) с: $(cat /tmp/wait_a.log)"

  # 10b. Блокировку держит чужой процесс 8 секунд — ждём и продолжаем.
  ( exec 9< /var/lib/dpkg/lock-frontend; sleep 8 ) &
  sleep 1
  start=$SECONDS
  ( wait_for_apt ) > /tmp/wait_b.log 2>&1; rc=$?
  elapsed=$((SECONDS - start))
  wait
  [ "$rc" -eq 0 ] && [ "$elapsed" -ge 5 ] && grep -q "Жду" /tmp/wait_b.log \
    && pass "apt занят → скрипт ждёт ($elapsed с) и продолжает" \
    || fail "apt занят: rc=$rc, ждал $elapsed с, вывод: $(cat /tmp/wait_b.log)"

  # 10c. Блокировка не отпускает дольше лимита — внятная ошибка, а не бесконечное ожидание.
  ( exec 9< /var/lib/dpkg/lock-frontend; sleep 14 ) &
  sleep 1
  out="$( ( APT_WAIT_MAX=6 wait_for_apt ) 2>&1 )"; rc=$?
  wait
  [ "$rc" -ne 0 ] && printf '%s' "$out" | grep -q "apt занят" \
    && pass "блокировка не отпускает → ошибка по таймауту" \
    || fail "таймаут ожидания apt: rc=$rc, вывод: $out"

  # 10d. fuser нет в системе — ждать нечем, функция молча пропускает ожидание.
  ( PATH=/nonexistent wait_for_apt ) > /tmp/wait_d.log 2>&1; rc=$?
  [ "$rc" -eq 0 ] && pass "нет fuser → ожидание пропускается без ошибки" || fail "без fuser rc=$rc: $(cat /tmp/wait_d.log)"
fi

echo
echo "итого: $PASS ok, $FAIL FAIL"
[ "$FAIL" -eq 0 ]
