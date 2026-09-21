FROM node:22-slim

WORKDIR /app

COPY package.json package-lock.json ./
# sharp тянет тяжёлые платформенные бинарники (@img/sharp-*) — retries/timeout
# на случай сетевых обрывов при их загрузке (найдено живьём 2026-09-22).
RUN npm config set fetch-retries 5 && npm config set fetch-retry-mintimeout 20000 \
    && npm config set maxsockets 3 && npm ci

# Baileys генерирует превью-кадр для outbound-видео через ffmpeg
# (extractVideoThumb, node_modules/@whiskeysockets/baileys) — без него
# jpegThumbnail тихо не заполняется (ошибка гасится внутри библиотеки),
# видео уходит клиенту без превью. Найдено живой проверкой 2026-09-22.
# После npm ci (не до) — не инвалидирует закэшированный npm-слой лишний раз.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY . .

EXPOSE 8080

CMD ["npm", "run", "dev"]
