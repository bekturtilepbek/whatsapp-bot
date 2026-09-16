// Нормализация proto.IWebMessageInfo (Baileys) -> inbound.text по контракту.
// Ноль бизнес-логики (ADR-002): фильтры групп/чёрного списка/графика — дело
// worker'а (Блок 2). Здесь только форма события; from_me тоже нормализуется —
// нужен worker'у для детекта ответа менеджера (handoff, Блок 3).
import { getContentType, jidDecode, toNumber, type WAMessage } from "@whiskeysockets/baileys";

import type { InboundText } from "../contracts/events.js";

// Соответствие FEATURES.md 2.6 (SUPPORTED_MEDIA_TYPES): image/video/audio/document/sticker.
const MEDIA_TYPE_BY_CONTENT_KEY: Partial<Record<string, string>> = {
  imageMessage: "image",
  videoMessage: "video",
  audioMessage: "audio",
  documentMessage: "document",
  stickerMessage: "sticker",
};

interface LocationMessageContent {
  degreesLatitude?: number | null;
  degreesLongitude?: number | null;
  name?: string | null;
  address?: string | null;
}

// FEATURES.md 9.x — геолокация клиента раньше пропадала целиком (ни текста,
// ни известного media_type — gateway отбрасывал сообщение полностью). Своего
// поля контракта не заводим: координаты рендерятся читаемым текстом и идут
// обычным текстовым путём — LLM видит их как часть диалога без изменений
// на стороне worker'а.
function extractLocationText(location: LocationMessageContent): string {
  const lat = location.degreesLatitude;
  const long = location.degreesLongitude;
  if (lat == null || long == null) return "";
  const label = [location.name, location.address].filter(Boolean).join(", ");
  const prefix = label ? `[Геолокация] ${label}` : "[Геолокация]";
  return `${prefix}\nhttps://maps.google.com/?q=${lat},${long}`;
}

function extractText(contentType: string | undefined, content: Record<string, unknown> | undefined): string {
  if (!contentType || !content) return "";
  switch (contentType) {
    case "conversation":
      return typeof content.conversation === "string" ? content.conversation : "";
    case "extendedTextMessage":
      return typeof content.extendedTextMessage === "object" && content.extendedTextMessage
        ? ((content.extendedTextMessage as { text?: string }).text ?? "")
        : "";
    case "locationMessage":
      return typeof content.locationMessage === "object" && content.locationMessage
        ? extractLocationText(content.locationMessage as LocationMessageContent)
        : "";
    default: {
      // Медиа-сообщения могут нести подпись (caption) — считаем это текстом.
      const body = content[contentType] as { caption?: string } | undefined;
      return body?.caption ?? "";
    }
  }
}

interface QuotedContext {
  text: string | null;
  mediaType: string | null;
}

function extractQuotedContext(
  contentType: string | undefined,
  content: Record<string, unknown> | undefined,
): QuotedContext {
  if (!contentType || !content) return { text: null, mediaType: null };
  const body = content[contentType] as { contextInfo?: { quotedMessage?: WAMessage["message"] } } | undefined;
  const quoted = body?.contextInfo?.quotedMessage;
  if (!quoted) return { text: null, mediaType: null };
  const quotedType = getContentType(quoted);
  const text = extractText(quotedType, quoted as Record<string, unknown>);
  if (text) return { text, mediaType: null };
  // Цитата на медиа без подписи — в V1 (resolveQuotedContext) контекст всё
  // равно не терялся, боту передавался тип цитируемого сообщения.
  const mediaType = quotedType ? (MEDIA_TYPE_BY_CONTENT_KEY[quotedType] ?? null) : null;
  return { text: null, mediaType };
}

/**
 * @returns null, если сообщение не текстовое и не из поддерживаемых медиатипов
 * (реакции, опросы, служебные протокольные сообщения и т.п. — вне скоупа Блока 1).
 */
export function normalizeInboundMessage(botId: string, msg: WAMessage): InboundText | null {
  const chatId = msg.key.remoteJid;
  const waMsgId = msg.key.id;
  if (!chatId || !waMsgId || !msg.message) return null;

  const contentType = getContentType(msg.message);
  const content = msg.message as unknown as Record<string, unknown>;
  const text = extractText(contentType, content);
  const mediaType = contentType ? (MEDIA_TYPE_BY_CONTENT_KEY[contentType] ?? null) : null;

  if (!text && !mediaType) return null; // реакции/опросы/протокольные апдейты — пропускаем

  const senderJid = msg.key.participant ?? chatId;
  const decoded = jidDecode(senderJid);
  // LID-контакты: Baileys этой версии не отдаёt сопоставление с телефонным JID
  // на уровне сообщения (см. FEATURES.md 9.2) — пишем то, что реально пришло,
  // sender_lid не заполняем здесь; матчинг wa_id<->lid — задача Block 2.
  const senderWaId = decoded?.user ?? senderJid;
  const quoted = extractQuotedContext(contentType, content);

  return {
    type: "inbound.text",
    bot_id: botId,
    wa_msg_id: waMsgId,
    chat_id: chatId,
    sender_wa_id: senderWaId,
    sender_lid: null,
    from_me: msg.key.fromMe ?? false,
    text,
    quoted_text: quoted.text,
    quoted_media_type: quoted.mediaType,
    media_type: mediaType,
    ts: toNumber(msg.messageTimestamp) * 1000,
  };
}
