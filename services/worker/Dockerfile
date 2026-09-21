# Контекст сборки — корень репозитория (нужен доступ к libs/*)
FROM python:3.12-slim

# structlog нигде не настроен через structlog.configure() — используется его
# дефолтный PrintLoggerFactory (обычный print() в stdout). Без этой переменной
# CPython буферизует stdout полностью, раз он не TTY (обычная ситуация в
# Docker) — строки лога могут не долетать до `docker logs`/Loki минутами, а
# при аварийном падении контейнера (OOM, необработанный сигнал) теряются
# навсегда вместе с недописанным буфером (найдено живьём 2026-09-21: реальное
# сообщение уже осело в БД, а в логах воркера не было вообще ничего).
ENV PYTHONUNBUFFERED=1

# FEATURES.md 2.2 — голосовое перед STT перекодируется в mp3 (worker/pipeline/audio.py).
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY libs /app/libs
COPY services/worker /app/services/worker

RUN pip install --no-cache-dir -e /app/libs/core -e /app/libs/db -e /app/libs/llm -e /app/libs/integrations -e /app/libs/scheduling -e /app/libs/tools -e /app/services/worker

EXPOSE 8081

CMD ["python", "-m", "worker.main"]
