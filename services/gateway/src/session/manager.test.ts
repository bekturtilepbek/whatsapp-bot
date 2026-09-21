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

    // Не настоящий JPEG — Sharp не сможет построить превью, sendImage должен
    // деградировать в отправку без jpegThumbnail, а не упасть.
    const image = Buffer.from("fake-jpeg-bytes");
    await sessions.sendImage("bot-1", "996700000000@s.whatsapp.net", image, "image/jpeg", "img-msg-1");

    expect(sendMessageMock).toHaveBeenCalledWith(
      "996700000000@s.whatsapp.net",
      { image, mimetype: "image/jpeg" },
      { messageId: "img-msg-1" },
    );
  });

  it("sendImage attaches a jpegThumbnail built from the real image bytes", async () => {
    // Обходит гонку внутри Baileys (encryptedStream пишет originalFilePath
    // асинхронно, не дожидаясь flush, пока Promise.all параллельно читает тот
    // же файл для превью — живой баг, найден 2026-09-22) — считаем превью
    // сами из буфера, который уже целиком в памяти.
    const sharp = (await import("sharp")).default;
    const image = await sharp({
      create: { width: 4, height: 4, channels: 3, background: { r: 255, g: 0, b: 0 } },
    })
      .jpeg()
      .toBuffer();
    const sessions = new SessionManager(makeFakePool(), makeFakeRedis(), makeFakeLogger(), makeFakeStorage());
    await sessions.startSession("bot-1");

    await sessions.sendImage("bot-1", "996700000000@s.whatsapp.net", image, "image/jpeg", "img-msg-2");

    const [, content] = sendMessageMock.mock.calls.at(-1)!;
    expect(typeof (content as { jpegThumbnail?: string }).jpegThumbnail).toBe("string");
    expect((content as { jpegThumbnail?: string }).jpegThumbnail!.length).toBeGreaterThan(0);
  });

  it("sendDocument passes clientMsgId as Baileys messageId with document+mimetype+fileName", async () => {
    const sessions = new SessionManager(makeFakePool(), makeFakeRedis(), makeFakeLogger(), makeFakeStorage());
    await sessions.startSession("bot-1");

    const document = Buffer.from("fake-pdf-bytes");
    await sessions.sendDocument(
      "bot-1", "996700000000@s.whatsapp.net", document, "application/pdf", "price-list.pdf", "doc-msg-1",
    );

    expect(sendMessageMock).toHaveBeenCalledWith(
      "996700000000@s.whatsapp.net",
      { document, mimetype: "application/pdf", fileName: "price-list.pdf" },
      { messageId: "doc-msg-1" },
    );
  });

  it("sendVideo passes clientMsgId as Baileys messageId with video+mimetype", async () => {
    const sessions = new SessionManager(makeFakePool(), makeFakeRedis(), makeFakeLogger(), makeFakeStorage());
    await sessions.startSession("bot-1");

    const video = Buffer.from("fake-mp4-bytes");
    await sessions.sendVideo("bot-1", "996700000000@s.whatsapp.net", video, "video/mp4", "video-msg-1");

    expect(sendMessageMock).toHaveBeenCalledWith(
      "996700000000@s.whatsapp.net",
      { video, mimetype: "video/mp4" },
      { messageId: "video-msg-1" },
    );
  });

  // FEATURES.md 9.10 — живьём проверено на реальном номере (спайк 2026-09-12):
  // реакция доставляется и отображается корректно.
  it("sendReaction reacts to the client's message (fromMe:false), not our own", async () => {
    const sessions = new SessionManager(makeFakePool(), makeFakeRedis(), makeFakeLogger(), makeFakeStorage());
    await sessions.startSession("bot-1");

    await sessions.sendReaction(
      "bot-1",
      "996700000000@s.whatsapp.net",
      "3EB0C767D82A1B0C4A5F",
      "👍",
      "reaction-msg-1",
    );

    expect(sendMessageMock).toHaveBeenCalledWith(
      "996700000000@s.whatsapp.net",
      {
        react: {
          text: "👍",
          key: { remoteJid: "996700000000@s.whatsapp.net", id: "3EB0C767D82A1B0C4A5F", fromMe: false },
        },
      },
      { messageId: "reaction-msg-1" },
    );
  });
});

// FEATURES.md 6.17 — дашборд узнаёт живой статус сессии только из
// bot_sessions.status/last_seen (событие session.status само по себе никуда
// не оседает, worker его дропает — см. consumer.py). publishStatus приватный,
// вызываем напрямую — ровно то, что реально дёргается на connection.update.
describe("SessionManager - persists session status to Postgres", () => {
  it("writes status and last_seen via UPSERT on bot_sessions", async () => {
    const pool = makeFakePool();
    const sessions = new SessionManager(pool, makeFakeRedis(), makeFakeLogger(), makeFakeStorage());

    await (sessions as any).publishStatus("bot-1", "open");

    expect(pool.query).toHaveBeenCalledWith(expect.stringContaining("bot_sessions"), [
      "bot-1",
      "open",
    ]);
  });

  it("does not throw when the DB write fails", async () => {
    const pool = {
      query: vi.fn(async () => {
        throw new Error("connection refused");
      }),
    } as unknown as Pool;
    const logger = makeFakeLogger();
    const sessions = new SessionManager(pool, makeFakeRedis(), logger, makeFakeStorage());

    await expect((sessions as any).publishStatus("bot-1", "qr")).resolves.toBeUndefined();
    expect(logger.error).toHaveBeenCalledWith(
      expect.objectContaining({ botId: "bot-1", status: "qr" }),
      "failed to persist session status",
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
