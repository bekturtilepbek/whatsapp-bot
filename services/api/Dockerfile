# Контекст сборки — корень репозитория (нужен доступ к libs/*)
FROM python:3.12-slim

WORKDIR /app

COPY libs /app/libs
COPY services/api /app/services/api

RUN pip install --no-cache-dir -e /app/libs/core -e /app/libs/db -e /app/libs/integrations -e /app/libs/llm -e /app/libs/scheduling -e /app/libs/tools -e /app/services/api

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
