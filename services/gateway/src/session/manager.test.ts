// SessionManager.sendText: messageId=clientMsgId — критично для Блока 3
// (handoff различает наш echo от ручного ответа менеджера по совпадению
// wa_msg_id входящего from_me-события с client_msg_id, который мы сами
// проставили при отправке). Реальный Baileys-сокет подменён фейком —
// makeWASocket и fetchLatestBaileysVersion замоканы, остальной модуль настоящий.
import type { Pool } from "pg";
import { beforeEach, describe, expect, it, vi } from "vitest";

const sendMessageMock = vi.fn(async () => undefined);
const sendPresenceUpdateMock = vi.fn(async () => undefined);

function makeFakeSocket() {
  return {
    ev: { on: vi.fn() },
    sendMessage: sendMessageMock,
    sendPresenceUpdate: sendPresenceUpdateMock,
    user: { id: "996700000000:1@s.whatsapp.net" },
    logout: vi.fn(async () => undefined),
    end: vi.fn(),
  };
}

vi.mock("@whiskeysockets/baileys", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@whiskeysockets/baileys")>();
  return {
    ...actual,
    default: vi.fn(() => makeFakeSocket()),
    fetchLatestBaileysVersion: vi.fn(async () => ({ version: [2, 3000, 0] })),
  };
});

// vi.mock выше хостится vitest'ом перед всеми импортами модуля.
import { SessionManager } from "./manager.js";

function makeFakePool(): Pool {
  return {
    query: vi.fn(async () => ({ rows: [{ auth_state_text: null }] })),
  } as unknown as Pool;
}

function makeFakeRedis() {
  return { xadd: vi.fn(async () => "1-0") } as unknown as import("ioredis").Redis;
}

function makeFakeLogger(): import("../logger.js").TransportLogger {
  const logger = {
    level: "info",
    child: () => logger,
    trace: vi.fn(),
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  };
  return logger;
}

describe("SessionManager.sendText / sendTyping", () => {
  beforeEach(() => {
    sendMessageMock.mockClear();
    sendPresenceUpdateMock.mockClear();
  });

  it("passes clientMsgId as Baileys messageId when sending text", async () => {
    const sessions = new SessionManager(makeFakePool(), makeFakeRedis(), makeFakeLogger());
    await sessions.startSession("bot-1");

    await sessions.sendText("bot-1", "996700000000@s.whatsapp.net", "привет", "abc123hex");

    expect(sendMessageMock).toHaveBeenCalledWith(
      "996700000000@s.whatsapp.net",
      { text: "привет" },
      { messageId: "abc123hex" },
    );
  });

  it("sendTyping sends a composing presence update", async () => {
    const sessions = new SessionManager(makeFakePool(), makeFakeRedis(), makeFakeLogger());
    await sessions.startSession("bot-1");

    await sessions.sendTyping("bot-1", "996700000000@s.whatsapp.net");

    expect(sendPresenceUpdateMock).toHaveBeenCalledWith("composing", "996700000000@s.whatsapp.net");
  });
});
