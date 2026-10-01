#!/usr/bin/env bash
# Первичная настройка ЧИСТОГО сервера Ubuntu 22.04/24.04 под прод-стек. Запускать от root.
#
# Идемпотентен — повторный запуск ничего не ломает, так и задумано: при первом
# запуске скрипт создаёт deploy-ключ и печатает его, вы добавляете ключ в GitHub, при
# втором запуске репозиторий клонируется.
#
# Репозиторий приватный и пока не склонирован, поэтому сам скрипт на сервер копируется
# руками (один раз):
#   scp infra/provision.sh root@<IP сервера>:/root/
#   ssh root@<IP сервера> 'REPO_URL=git@github.com:<владелец>/<репозиторий>.git bash /root/provision.sh'
#
# Что делает: ставит Docker (официальный репозиторий), создаёт swap, включает файрвол
# (22/80/443), создаёт deploy-ключ для GitHub и клонирует репозиторий в $INSTALL_DIR.
# .env и сам деплой — вручную по docs/RUNBOOK.md.
#
# Переменные окружения:
#   REPO_URL        адрес репозитория по SSH (git@github.com:владелец/репозиторий.git)
#   INSTALL_DIR     куда клонировать (по умолчанию /opt/platform)
#   DEPLOY_BRANCH   какую ветку клонировать (по умолчанию main)
#   SWAP_SIZE_GB    размер swap, если его ещё нет (по умолчанию 2)
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/platform}"
REPO_URL="${REPO_URL:-}"
BRANCH="${DEPLOY_BRANCH:-main}"
SWAP_SIZE_GB="${SWAP_SIZE_GB:-2}"
SSH_DIR="$HOME/.ssh"
DEPLOY_KEY="$SSH_DIR/platform_deploy"

log() { printf '\n==> %s\n' "$*"; }
die() { printf '\nОШИБКА: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "запускайте от root (ssh root@... или sudo)"
[ -r /etc/os-release ] || die "не удалось определить ОС"
# shellcheck disable=SC1091
. /etc/os-release
[ "${ID:-}" = "ubuntu" ] || die "скрипт рассчитан на Ubuntu (здесь: ${ID:-неизвестно})"

export DEBIAN_FRONTEND=noninteractive

# --- 1. Базовые пакеты ---------------------------------------------------------------
log "Базовые пакеты"
apt-get update -qq
apt-get install -y -qq ca-certificates curl git ufw python3 >/dev/null

# --- 2. Docker -------------------------------------------------------------------------
if docker compose version >/dev/null 2>&1; then
  log "Docker уже установлен: $(docker --version)"
else
  log "Установка Docker (официальный репозиторий docker.com)"
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin >/dev/null
  systemctl enable --now docker
  log "Docker установлен: $(docker --version)"
fi

# --- 3. Swap ---------------------------------------------------------------------------
# Сборка образов (next build, npm ci) на сервере на 2–4 ГБ без swap упирается в OOM.
if [ -n "$(swapon --show --noheadings 2>/dev/null)" ]; then
  log "Swap уже есть: $(swapon --show --noheadings | awk '{print $1, $3}' | tr '\n' ' ')"
else
  log "Создание swap ${SWAP_SIZE_GB} ГБ"
  fallocate -l "${SWAP_SIZE_GB}G" /swapfile
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  echo 'vm.swappiness=10' > /etc/sysctl.d/99-swappiness.conf
  sysctl -q -p /etc/sysctl.d/99-swappiness.conf
fi

# --- 4. Файрвол -------------------------------------------------------------------------
# 22 — SSH (правило ПЕРВЫМ, иначе включение файрвола отрежет вас от сервера),
# 80/443 — Caddy (80 нужен и для выпуска сертификата), 443/udp — HTTP/3.
# ВАЖНО: ufw НЕ фильтрует порты, опубликованные самим Docker (он правит iptables
# в обход). Наружу смотрят только 80/443 caddy — это обеспечено тем, что
# postgres/redis в compose не публикуются, а api/admin-web привязаны к 127.0.0.1.
log "Файрвол (ufw): 22, 80, 443"
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw allow 22/tcp >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw allow 443/udp >/dev/null
ufw --force enable >/dev/null
# В переменную, а не `ufw status | head`: при pipefail head закрывает канал раньше
# конца вывода, ufw получает SIGPIPE, и весь скрипт падает на ровном месте.
ufw_status="$(ufw status)"
printf '%s\n' "$ufw_status" | sed -n '1,8p'

# --- 5. Deploy-ключ для GitHub -------------------------------------------------------------
log "Deploy-ключ для GitHub"
install -d -m 700 "$SSH_DIR"
if [ ! -f "$DEPLOY_KEY" ]; then
  ssh-keygen -q -t ed25519 -N "" -C "platform-deploy@$(hostname)" -f "$DEPLOY_KEY"
  echo "создан новый ключ $DEPLOY_KEY"
fi

# Ключи хоста GitHub берём по HTTPS из их API — доверие опирается на сертификат
# api.github.com, а не на «принять отпечаток при первом подключении».
touch "$SSH_DIR/known_hosts"
if ! grep -q '^github.com ' "$SSH_DIR/known_hosts"; then
  if keys="$(curl -fsS --max-time 20 https://api.github.com/meta 2>/dev/null | python3 -c '
import json, sys
for key in json.load(sys.stdin)["ssh_keys"]:
    print("github.com " + key)
' 2>/dev/null)" && [ -n "$keys" ]; then
    printf '%s\n' "$keys" >> "$SSH_DIR/known_hosts"
  else
    echo "ПРЕДУПРЕЖДЕНИЕ: не удалось получить ключи GitHub из API — берём через ssh-keyscan (доверие при первом подключении)." >&2
    echo "Сверьте отпечаток с https://docs.github.com/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints" >&2
    ssh-keyscan -t ed25519 github.com >> "$SSH_DIR/known_hosts" 2>/dev/null
  fi
fi

if ! grep -q "$DEPLOY_KEY" "$SSH_DIR/config" 2>/dev/null; then
  cat >> "$SSH_DIR/config" <<EOF

Host github.com
  IdentityFile $DEPLOY_KEY
  IdentitiesOnly yes
EOF
  chmod 600 "$SSH_DIR/config"
fi

# --- 6. Клонирование ----------------------------------------------------------------------------
print_key_help() {
  cat <<EOF

Откройте репозиторий на GitHub → Settings → Deploy keys → Add deploy key,
вставьте ключ ниже (галочку «Allow write access» НЕ ставьте — серверу нужно только чтение)
и запустите ту же команду ещё раз:

$(cat "$DEPLOY_KEY.pub")

EOF
}

if [ -d "$INSTALL_DIR/.git" ]; then
  log "Репозиторий уже склонирован в $INSTALL_DIR"
elif [ -z "$REPO_URL" ]; then
  log "REPO_URL не задан — клонирование пропущено"
  echo "Повторите запуск с REPO_URL=git@github.com:<владелец>/<репозиторий>.git"
  print_key_help
  exit 0
else
  log "Клонирование $REPO_URL ($BRANCH) в $INSTALL_DIR"
  if git clone --quiet --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"; then
    :
  else
    print_key_help
    die "не удалось клонировать — вероятно, ключ ещё не добавлен в GitHub (или ветки '$BRANCH' нет в репозитории)"
  fi
fi

cat <<EOF

Сервер готов. Дальше (docs/RUNBOOK.md, «Первый деплой»):
  1. cd $INSTALL_DIR && cp .env.example .env   # заполнить, секреты сгенерировать
  2. $INSTALL_DIR/infra/deploy.sh
EOF
