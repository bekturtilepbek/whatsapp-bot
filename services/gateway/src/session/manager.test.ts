// SessionManager.sendText: messageId=clientMsgId — критично для Блока 3
// (handoff различает наш echo от ручного ответа менеджера по совпадению
// wa_msg_id входящего from_me-события с client_msg_id, который мы сами
// проставили при отправке). Реальный Baileys-сокет подменён фейком —
// makeWASocket и fetchLatestBaileysVersion замоканы, остальной модуль настоящий.
import type { Pool } from "pg";
import { beforeEach, describe, expect, it, vi } from "vitest";

const sendMessageMock = vi.fn(async () => undefined);
const sendPresenceUpdateMock = vi.fn(async () => undefined);
const readMessagesMock = vi.fn(async () => undefined);

function makeFakeSocket() {
  return {
    ev: { on: vi.fn() },
    sendMessage: sendMessageMock,
    sendPresenceUpdate: sendPresenceUpdateMock,
    readMessages: readMessagesMock,
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
const { default: makeWASocketMock, downloadMediaMessage } = await import("@whiskeysockets/baileys");
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
    readMessagesMock.mockClear();
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

  // FEATURES.md 1.11 — NEW, не было в V1.
  it("sendSeen marks the client's message read (fromMe:false), not our own", async () => {
    const sessions = new SessionManager(makeFakePool(), makeFakeRedis(), makeFakeLogger(), makeFakeStorage());
    await sessions.startSession("bot-1");

    await sessions.sendSeen("bot-1", "996700000000@s.whatsapp.net", "3EB0C767D82A1B0C4A5F");

    expect(readMessagesMock).toHaveBeenCalledWith([
      { remoteJid: "996700000000@s.whatsapp.net", id: "3EB0C767D82A1B0C4A5F", fromMe: false },
    ]);
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

  // Живой баг (2026-09-28): connect() зовёт publishStatus("connecting") без
  // ожидания завершения перед тем, как хендшейк Baileys может уже дойти до
  // "open" и вызвать свой собственный publishStatus("open") — два pool.query()
  // гонялись без синхронизации, и чей ответ от Postgres придёт позже, тот и
  // побеждал в UPSERT НЕЗАВИСИМО от порядка вызова. На реальном стенде это
  // откатило статус рабочего, отвечающего в WhatsApp бота обратно на
  // "connecting" бессрочно (бейдж в кабинете показывал "не подключён").
  // Здесь эмулируем именно эту гонку: "connecting" вызван ПЕРВЫМ, но его
  // запрос к Postgres искусственно медленнее, чем у "open", вызванного ПОСЛЕ.
  it("applies status writes to Postgres in call order, not in DB-response order (race regression)", async () => {
    const order: string[] = [];
    const pool = {
      query: vi.fn(async (_sql: string, params: [string, string]) => {
        const delayMs = params[1] === "connecting" ? 20 : 0;
        await new Promise((resolve) => setTimeout(resolve, delayMs));
        order.push(params[1]);
        return { rows: [] };
      }),
    } as unknown as Pool;
    const sessions = new SessionManager(pool, makeFakeRedis(), makeFakeLogger(), makeFakeStorage());

    await Promise.all([
      (sessions as any).publishStatus("bot-1", "connecting"),
      (sessions as any).publishStatus("bot-1", "open"),
    ]);

    expect(order).toEqual(["connecting", "open"]);
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

// Живой баг (security review, 2026-09-28): connect() делает два await (auth-
// state из Postgres, версия Baileys) ДО того, как сессия попадает в
// this.sessions — sessions.has() в startSession() была единственной защитой
// от двойного запуска, и два близких вызова (два /qr/:botId подряд, поллинг
// дашборда) оба проходили её до того, как первый успевал дойти до
// sessions.set, создавая два сокета с одними и теми же credentials.
describe("SessionManager.startSession - concurrent calls for the same bot", () => {
  it("only builds one Baileys socket when startSession is called twice before the first resolves", async () => {
    const callsBefore = makeWASocketMock.mock.calls.length;
    const sessions = new SessionManager(makeFakePool(), makeFakeRedis(), makeFakeLogger(), makeFakeStorage());

    await Promise.all([sessions.startSession("bot-1"), sessions.startSession("bot-1")]);

    expect(makeWASocketMock.mock.calls.length - callsBefore).toBe(1);
  });

  it("waitForQr (the real /qr/:botId path) calling startSession concurrently with another caller still builds one socket", async () => {
    const callsBefore = makeWASocketMock.mock.calls.length;
    const sessions = new SessionManager(makeFakePool(), makeFakeRedis(), makeFakeLogger(), makeFakeStorage());

    // waitForQr rejects on timeout if no "qr" event ever fires (this fake
    // socket never emits one) — only the socket-count guarantee matters
    // here, so a short timeout keeps the test fast regardless.
    await Promise.allSettled([sessions.startSession("bot-2"), sessions.waitForQr("bot-2", 20)]);

    expect(makeWASocketMock.mock.calls.length - callsBefore).toBe(1);
  });
});

/** Достаёт хендлер, который connect() зарегистрировал через sock.ev.on(event, ...) на ПОСЛЕДНЕМ созданном фейковом сокете. */
function lastRegisteredHandler(eventName: string): (...args: unknown[]) => void {
  const socket = makeWASocketMock.mock.results.at(-1)!.value as { ev: { on: ReturnType<typeof vi.fn> } };
  const call = socket.ev.on.mock.calls.find(([name]: [string]) => name === eventName);
  if (!call) throw new Error(`no listener registered for ${eventName}`);
  return call[1] as (...args: unknown[]) => void;
}

// Живой класс бага (security review, 2026-09-28): connection.update и
// реконнект-таймер вызывали onConnectionUpdate()/connect() через "void" —
// необработанный reject там становится unhandledRejection и роняет ВЕСЬ
// процесс gateway (тот же класс, что уже нашли и закрыли в pool.ts/redis.ts).
describe("SessionManager - unhandled rejection safety on connection.update / reconnect", () => {
  it("logs (does not throw) when onConnectionUpdate's own DB call fails", async () => {
    const logger = makeFakeLogger();
    const pool = {
      query: vi.fn(async (sql: string) => {
        // markLinked (вызывается на connection:"open") пишет phone — эта
        // проверка отличает его от остальных запросов той же функции.
        if (sql.includes("phone")) throw new Error("connection refused");
        if (sql.startsWith("SELECT")) return { rows: [{ auth_state_text: null }] };
        return { rows: [] };
      }),
    } as unknown as Pool;
    const sessions = new SessionManager(pool, makeFakeRedis(), logger, makeFakeStorage());
    await sessions.startSession("bot-open-fail");

    const onConnectionUpdate = lastRegisteredHandler("connection.update");
    // Не await'им — ровно так же, как реальный sock.ev.emit: слушатель не
    // может быть async из коробки, ошибка внутри уходит в отдельный промис.
    onConnectionUpdate({ connection: "open" });
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(logger.error).toHaveBeenCalledWith(
      expect.objectContaining({ botId: "bot-open-fail" }),
      "onConnectionUpdate failed",
    );
  });

  it("logs and clears the stale session entry when a scheduled reconnect's connect() fails", async () => {
    vi.useFakeTimers();
    try {
      const logger = makeFakeLogger();
      let failNextSelect = false;
      const pool = {
        query: vi.fn(async (sql: string) => {
          if (sql.startsWith("SELECT") && failNextSelect) throw new Error("connection refused");
          if (sql.startsWith("SELECT")) return { rows: [{ auth_state_text: null }] };
          return { rows: [] };
        }),
      } as unknown as Pool;
      const sessions = new SessionManager(pool, makeFakeRedis(), logger, makeFakeStorage());
      await sessions.startSession("bot-reconnect-fail");

      const onConnectionUpdate = lastRegisteredHandler("connection.update");
      // Следующий connect() (внутри отложенного реконнекта) должен упасть на
      // чтении auth-state — имитирует сбой Postgres именно в момент реконнекта.
      failNextSelect = true;
      onConnectionUpdate({ connection: "close", lastDisconnect: { error: undefined } });
      await vi.advanceTimersByTimeAsync(0); // даёт onConnectionUpdate дойти до setTimeout
      await vi.advanceTimersByTimeAsync(1000); // RECONNECT_BASE_DELAY_MS
      await vi.advanceTimersByTimeAsync(0); // даёт упавшему connect() долететь до .catch()

      expect(logger.error).toHaveBeenCalledWith(
        expect.objectContaining({ botId: "bot-reconnect-fail" }),
        "scheduled reconnect failed",
      );

      // Без очистки эта запись осталась бы в this.sessions НАВСЕГДА —
      // startSession видел бы sessions.has() === true и никогда не поднял
      // бы сессию заново без рестарта всего gateway.
      const callsBefore = makeWASocketMock.mock.calls.length;
      failNextSelect = false;
      await sessions.startSession("bot-reconnect-fail");
      expect(makeWASocketMock.mock.calls.length - callsBefore).toBe(1);
    } finally {
      vi.useRealTimers();
    }
  });
});
