// 1.9 + 2.7: лимит размера ДО скачивания (грабля: причина OOM прошлой
// версии), скачивание+расшифровка через Baileys, загрузка в Storage. Любой
// сбой на этом пути НЕ блокирует приём сообщения: событие уходит без
// storage_key, worker откатывается на существующий media-fallback (2.6).
import { downloadMediaMessage, getContentType, toNumber, type WAMessage } from "@whiskeysockets/baileys";
import type { Pool } from "pg";

import { getBotMediaMaxSizeBytes } from "../db/bots.js";
import type { TransportLogger } from "../logger.js";
import type { Storage } from "../storage/types.js";
import { withTimeout } from "../utils/timeout.js";

const DOWNLOAD_TIMEOUT_MS = 20_000;
const UPLOAD_TIMEOUT_MS = 20_000;
// Локальный Postgres SELECT по индексу — не CDN-вызов, 5с более чем достаточно.
const LIMIT_LOOKUP_TIMEOUT_MS = 5_000;

// wa_msg_id управляется отправителем (Baileys его не валидирует) и идёт прямо
// в storage key → без проверки это path traversal (см. финальный review, Fix 1).
// Реальные id вида "3EB0C767D26A1D6" этому паттерну соответствуют; botId тоже
// проверяем — дешёвая подстраховка, хоть он и не под контролем отправителя.
const SAFE_ID_PATTERN = /^[A-Za-z0-9._-]+$/;

export interface MediaAttachment {
  storage_key: string;
  mime_type: string;
  size_bytes: number;
}

interface MediaFileInfo {
  mimeType: string;
  fileLength: number;
}

/** Чистая функция — достаёт mimetype/fileLength из протобаф-сообщения, без сети. */
export function extractMediaFileInfo(msg: WAMessage): MediaFileInfo | null {
  if (!msg.message) return null;
  const contentType = getContentType(msg.message);
  if (!contentType) return null;
  const content = msg.message as unknown as Record<string, unknown>;
  const body = content[contentType] as { mimetype?: string; fileLength?: number } | undefined;
  if (!body?.mimetype) return null;
  const fileLength = toNumber(body.fileLength);
  if (!fileLength) return null; // неизвестный размер — не можем проверить лимит, пропускаем безопасно
  return { mimeType: body.mimetype, fileLength };
}

export async function attachMedia(
  pool: Pool,
  storage: Storage,
  logger: TransportLogger,
  botId: string,
  waMsgId: string,
  msg: WAMessage,
): Promise<MediaAttachment | null> {
  if (!SAFE_ID_PATTERN.test(waMsgId) || !SAFE_ID_PATTERN.test(botId)) {
    logger.warn({ botId, waMsgId }, "media_skipped: unsafe_wa_msg_id");
    return null;
  }

  const info = extractMediaFileInfo(msg);
  if (!info) {
    logger.warn({ botId, waMsgId }, "media_skipped: no file info in message");
    return null;
  }

  let maxBytes: number;
  try {
    maxBytes = await withTimeout(getBotMediaMaxSizeBytes(pool, botId), LIMIT_LOOKUP_TIMEOUT_MS, "media limit lookup");
  } catch (err) {
    logger.warn({ err, botId, waMsgId }, "media_skipped: limit_lookup_failed");
    return null;
  }
  if (info.fileLength > maxBytes) {
    logger.warn({ botId, waMsgId, fileLength: info.fileLength, maxBytes }, "media_skipped: too_large");
    return null;
  }

  let bytes: Buffer;
  try {
    bytes = await withTimeout(
      // reuploadRequest — для истёкшего media-ключа (CDN вернул 404/410); тут
      // нет сокета, чтобы его запросить у WhatsApp, поэтому просто отклоняем —
      // ниже это ловится как обычный download_failed, приём не блокируется.
      downloadMediaMessage(msg, "buffer", {}, { logger, reuploadRequest: () => Promise.reject(new Error("media reupload not supported")) }),
      DOWNLOAD_TIMEOUT_MS,
      "media download",
    );
  } catch (err) {
    logger.warn({ err, botId, waMsgId }, "media_skipped: download_failed");
    return null;
  }

  // fileLength — это то, что заявил отправитель; враждебный клиент может
  // занизить его и залить сколько угодно байт — downloadMediaMessage всё
  // равно буферизует их целиком в памяти. Бэкстоп после скачивания, не
  // замена пре-чеку выше (грабля CLAUDE.md — лимит ДО скачивания, тут —
  // страховка на случай, если сам факт скачивания уже произошёл).
  if (bytes.length > maxBytes) {
    logger.warn({ botId, waMsgId, size: bytes.length, maxBytes }, "media_skipped: downloaded_size_exceeds_limit");
    return null;
  }

  const key = `bots/${botId}/media/${waMsgId}`;
  try {
    await withTimeout(storage.put(key, bytes, info.mimeType), UPLOAD_TIMEOUT_MS, "storage put");
  } catch (err) {
    logger.warn({ err, botId, waMsgId }, "media_skipped: upload_failed");
    return null;
  }

  return { storage_key: key, mime_type: info.mimeType, size_bytes: bytes.length };
}
