#!/usr/bin/env bash
# Тест infra/provision.sh: запускает provision_inner.sh в чистом контейнере ubuntu:24.04.
# Проверяет логику ключей и клонирования; установка Docker, swap и файрвол не
# запускаются (они меняют ядро хоста) и проверяются только на настоящем сервере.
#
# Запуск: bash infra/tests/test_provision.sh   (нужен Docker; без него — пропуск)
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if ! docker info >/dev/null 2>&1; then
  echo "skip: Docker недоступен — тест provision.sh пропущен"
  exit 0
fi

# Windows (Git Bash): для docker -v нужен путь вида C:/..., конвертацию путей отключаем
# только на этот вызов. На Linux `pwd -W` не существует — берём обычный pwd.
infra_dir="$(cd "$REPO_ROOT/infra" && { pwd -W 2>/dev/null || pwd; })"

MSYS_NO_PATHCONV=1 docker run --rm -v "$infra_dir:/infra:ro" ubuntu:24.04 bash /infra/tests/provision_inner.sh
