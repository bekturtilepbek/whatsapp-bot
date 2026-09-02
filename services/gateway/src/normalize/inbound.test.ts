import { describe, expect, it } from "vitest";
import type { WAMessage } from "@whiskeysockets/baileys";
import { normalizeInboundMessage } from "./inbound.js";

const BOT_ID = "00000000-0000-0000-0000-000000000001";

function baseMessage(overrides: Partial<WAMessage> = {}): WAMessage {
  return {
    key: {
      remoteJid: "996700000000@s.whatsapp.net",
      id: "3EB0MSGID1",
      fromMe: false,
    },
    messageTimestamp: 1756800000, // секунды
    ...overrides,
  } as WAMessage;
}

describe("normalizeInboundMessage", () => {
  it("normalizes plain conversation text", () => {
    const msg = baseMessage({ message: { conversation: "Привет" } });
    const event = normalizeInboundMessage(BOT_ID, msg);
    expect(event).toMatchObject({
      type: "inbound.text",
      bot_id: BOT_ID,
      wa_msg_id: "3EB0MSGID1",
      chat_id: "996700000000@s.whatsapp.net",
      sender_wa_id: "996700000000",
      from_me: false,
      text: "Привет",
      quoted_text: null,
      media_type: null,
      ts: 1756800000000,
    });
  });

  it("normalizes extendedTextMessage text", () => {
    const msg = baseMessage({ message: { extendedTextMessage: { text: "Есть доставка?" } } });
    const event = normalizeInboundMessage(BOT_ID, msg);
    expect(event?.text).toBe("Есть доставка?");
  });

  it("extracts quoted text from contextInfo", () => {
    const msg = baseMessage({
      message: {
        extendedTextMessage: {
          text: "да, актуально",
          contextInfo: { quotedMessage: { conversation: "Товар ещё в наличии?" } },
        },
      },
    });
    const event = normalizeInboundMessage(BOT_ID, msg);
    expect(event?.quoted_text).toBe("Товар ещё в наличии?");
  });

  it("maps image message to media_type and picks up caption as text", () => {
    const msg = baseMessage({
      message: { imageMessage: { caption: "такой есть?", mimetype: "image/jpeg" } },
    });
    const event = normalizeInboundMessage(BOT_ID, msg);
    expect(event?.media_type).toBe("image");
    expect(event?.text).toBe("такой есть?");
  });

  it("image without caption yields empty text but media_type set", () => {
    const msg = baseMessage({ message: { imageMessage: { mimetype: "image/jpeg" } } });
    const event = normalizeInboundMessage(BOT_ID, msg);
    expect(event?.media_type).toBe("image");
    expect(event?.text).toBe("");
  });

  it("marks from_me messages (needed for handoff detection)", () => {
    const msg = baseMessage({
      key: { remoteJid: "996700000000@s.whatsapp.net", id: "X", fromMe: true },
      message: { conversation: "Отвечает менеджер" },
    });
    const event = normalizeInboundMessage(BOT_ID, msg);
    expect(event?.from_me).toBe(true);
  });

  it("returns null for unsupported content (e.g. reaction) with no text/media", () => {
    const msg = baseMessage({ message: { reactionMessage: { text: "👍" } } });
    expect(normalizeInboundMessage(BOT_ID, msg)).toBeNull();
  });

  it("returns null when chat_id or wa_msg_id is missing", () => {
    const msg = baseMessage({ key: { remoteJid: undefined, id: "X", fromMe: false } });
    (msg as { message?: unknown }).message = { conversation: "hi" };
    expect(normalizeInboundMessage(BOT_ID, msg)).toBeNull();
  });

  it("returns null when message body itself is absent", () => {
    const msg = baseMessage({ message: undefined });
    expect(normalizeInboundMessage(BOT_ID, msg)).toBeNull();
  });
});
