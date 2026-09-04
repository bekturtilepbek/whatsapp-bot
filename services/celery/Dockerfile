# Контекст сборки — корень репозитория (нужен доступ к libs/*)
FROM python:3.12-slim

WORKDIR /app

COPY libs /app/libs
COPY services/celery /app/services/celery

RUN pip install --no-cache-dir -e /app/libs/core -e /app/libs/db -e /app/libs/scheduling -e /app/services/celery

CMD ["celery", "-A", "tasks", "worker", "--loglevel=info"]
