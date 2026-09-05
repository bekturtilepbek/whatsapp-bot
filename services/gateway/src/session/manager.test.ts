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
    // Fix 2 (финальный review): гарантируем, что нижеидущие тесты действительно
    // ловят пропуск скачивания, а не просто попадание в замоканный happy-path.
    downloadMediaMessage: vi.fn(),
  };
});

// vi.mock выше хостится vitest'ом перед всеми импортами модуля.
const { downloadMediaMessage } = await import("@whiskeysockets/baileys");
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

function makeFakeStorage(): import("../storage/types.js").Storage {
  return { put: vi.fn(async () => undefined) };
}

describe("SessionManager.sendText / sendTyping", () => {
  beforeEach(() => {
    sendMessageMock.mockClear();
    sendPresenceUpdateMock.mockClear();
  });

  it("passes clientMsgId as Baileys messageId when sending text", async () => {
    const sessions = new SessionManager(makeFakePool(), makeFakeRedis(), makeFakeLogger(), makeFakeStorage());
    await sessions.startSession("bot-1");

    await sessions.sendText("bot-1", "996700000000@s.whatsapp.net", "привет", "abc123hex");

    expect(sendMessageMock).toHaveBeenCalledWith(
      "996700000000@s.whatsapp.net",
      { text: "привет" },
      { messageId: "abc123hex" },
    );
  });

  it("sendTyping sends a composing presence update", async () => {
    const sessions = new SessionManager(makeFakePool(), makeFakeRedis(), makeFakeLogger(), makeFakeStorage());
    await sessions.startSession("bot-1");

    await sessions.sendTyping("bot-1", "996700000000@s.whatsapp.net");

    expect(sendPresenceUpdateMock).toHaveBeenCalledWith("composing", "996700000000@s.whatsapp.net");
  });

  it("sendImage passes clientMsgId as Baileys messageId with image+mimetype", async () => {
    const sessions = new SessionManager(makeFakePool(), makeFakeRedis(), makeFakeLogger(), makeFakeStorage());
    await sessions.startSession("bot-1");

    const image = Buffer.from("fake-jpeg-bytes");
    await sessions.sendImage("bot-1", "996700000000@s.whatsapp.net", image, "image/jpeg", "img-msg-1");

    expect(sendMessageMock).toHaveBeenCalledWith(
      "996700000000@s.whatsapp.net",
      { image, mimetype: "image/jpeg" },
      { messageId: "img-msg-1" },
    );
  });
});

// Fix 2 (финальный review): gateway не должен скачивать/заливать медиа,
// которое worker всё равно отбросит до сохранения (группы, status@broadcast,
// from_me — см. is_ignored_chat в worker/pipeline/filters.py и отдельный путь
// handoff для from_me). onMessagesUpsert приватный — вызываем его напрямую,
// это ровно тот код, что реально подписан на "messages.upsert".
describe("SessionManager - media download skipped for group/broadcast/from_me", () => {
  function imageUpsert(overrides: { remoteJid: string; fromMe?: boolean }) {
    return {
      type: "notify" as const,
      messages: [
        {
          key: { remoteJid: overrides.remoteJid, id: "MSG1", fromMe: overrides.fromMe ?? false },
          message: { imageMessage: { mimetype: "image/jpeg", fileLength: 1000 } },
          messageTimestamp: 1_700_000_000,
        },
      ],
    };
  }

  beforeEach(() => {
    vi.mocked(downloadMediaMessage).mockClear();
  });

  it("does not download media for a group chat message", async () => {
    const storage = makeFakeStorage();
    const sessions = new SessionManager(makeFakePool(), makeFakeRedis(), makeFakeLogger(), storage);
    await sessions.startSession("bot-1");

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    await (sessions as any).onMessagesUpsert("bot-1", imageUpsert({ remoteJid: "123456-789@g.us" }));

    expect(downloadMediaMessage).not.toHaveBeenCalled();
    expect(storage.put).not.toHaveBeenCalled();
  });

  it("does not download media for status@broadcast", async () => {
    const storage = makeFakeStorage();
    const sessions = new SessionManager(makeFakePool(), makeFakeRedis(), makeFakeLogger(), storage);
    await sessions.startSession("bot-1");

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    await (sessions as any).onMessagesUpsert("bot-1", imageUpsert({ remoteJid: "status@broadcast" }));

    expect(downloadMediaMessage).not.toHaveBeenCalled();
    expect(storage.put).not.toHaveBeenCalled();
  });

  it("does not download media for a from_me message", async () => {
    const storage = makeFakeStorage();
    const sessions = new SessionManager(makeFakePool(), makeFakeRedis(), makeFakeLogger(), storage);
    await sessions.startSession("bot-1");

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    await (sessions as any).onMessagesUpsert(
      "bot-1",
      imageUpsert({ remoteJid: "996700000000@s.whatsapp.net", fromMe: true }),
    );

    expect(downloadMediaMessage).not.toHaveBeenCalled();
    expect(storage.put).not.toHaveBeenCalled();
  });
});
