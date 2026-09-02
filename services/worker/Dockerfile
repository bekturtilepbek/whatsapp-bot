# Контекст сборки — корень репозитория (нужен доступ к libs/*)
FROM python:3.12-slim

WORKDIR /app

COPY libs /app/libs
COPY services/worker /app/services/worker

RUN pip install --no-cache-dir -e /app/libs/core -e /app/libs/db -e /app/libs/llm -e /app/services/worker

EXPOSE 8081

CMD ["python", "-m", "worker.main"]
