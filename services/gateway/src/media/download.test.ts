import type { WAMessage } from "@whiskeysockets/baileys";
import { describe, expect, it, vi } from "vitest";

vi.mock("@whiskeysockets/baileys", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@whiskeysockets/baileys")>();
  return { ...actual, downloadMediaMessage: vi.fn() };
});

const { downloadMediaMessage } = await import("@whiskeysockets/baileys");
import { attachMedia, extractMediaFileInfo } from "./download.js";
import type { Storage } from "../storage/types.js";

function imageMessage(overrides: Record<string, unknown> = {}): WAMessage {
  return {
    key: { remoteJid: "996700000000@s.whatsapp.net", id: "MSG1", fromMe: false },
    message: { imageMessage: { mimetype: "image/jpeg", fileLength: 245760, ...overrides } },
  } as unknown as WAMessage;
}

describe("extractMediaFileInfo", () => {
  it("reads mimetype and fileLength from an image message", () => {
    expect(extractMediaFileInfo(imageMessage())).toEqual({
      mimeType: "image/jpeg",
      fileLength: 245760,
    });
  });

  it("returns null when fileLength is missing (can't verify limit — skip safely)", () => {
    expect(extractMediaFileInfo(imageMessage({ fileLength: undefined }))).toBeNull();
  });

  it("returns null when there is no media content", () => {
    const msg = {
      key: { remoteJid: "x", id: "MSG1", fromMe: false },
      message: { conversation: "text only" },
    } as unknown as WAMessage;
    expect(extractMediaFileInfo(msg)).toBeNull();
  });
});

function makeFakePool(maxBytes?: number) {
  const settings = maxBytes ? { media_max_size_bytes: maxBytes } : {};
  return { query: vi.fn(async () => ({ rows: [{ settings }] })) } as unknown as import("pg").Pool;
}

function makeFakeStorage(): Storage {
  return { put: vi.fn(async () => undefined) };
}

function makeFakeLogger(): TransportLoggerLike {
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
type TransportLoggerLike = ReturnType<typeof makeFakeLogger>;

describe("attachMedia", () => {
  it("skips download when fileLength exceeds the bot's limit", async () => {
    const pool = makeFakePool(1_000);
    const storage = makeFakeStorage();
    const result = await attachMedia(pool, storage, makeFakeLogger(), "bot-1", "MSG1", imageMessage());

    expect(result).toBeNull();
    expect(storage.put).not.toHaveBeenCalled();
    expect(downloadMediaMessage).not.toHaveBeenCalled();
  });

  it("downloads and uploads when within the limit, returning attachment fields", async () => {
    vi.mocked(downloadMediaMessage).mockResolvedValue(Buffer.from("bytes"));
    const pool = makeFakePool(10_000_000);
    const storage = makeFakeStorage();

    const result = await attachMedia(pool, storage, makeFakeLogger(), "bot-1", "MSG1", imageMessage());

    expect(result).toEqual({
      storage_key: "bots/bot-1/media/MSG1",
      mime_type: "image/jpeg",
      size_bytes: 5,
    });
    expect(storage.put).toHaveBeenCalledWith("bots/bot-1/media/MSG1", Buffer.from("bytes"), "image/jpeg");
  });

  // Fix 4 (финальный review): лимит-запрос обёрнут в withTimeout — таймаут
  // тоже приходит как обычное отклонённое промисе, этот тест ловит и его,
  // и обычную ошибку соединения через тот же catch-branch; отдельный
  // fake-timer тест на сам факт таймаута — overkill для этого случая.
  it("returns null when the limit lookup (Postgres) fails, without throwing", async () => {
    // downloadMediaMessage — общий мок на весь файл, предыдущие тесты уже
    // могли его вызвать; сбрасываем счётчик, чтобы проверить именно "не
    // вызван в этом сценарии", а не глобальный счётчик по всему файлу.
    vi.mocked(downloadMediaMessage).mockClear();
    const pool = { query: vi.fn(async () => { throw new Error("connection terminated"); }) } as unknown as import("pg").Pool;
    const storage = makeFakeStorage();

    const result = await attachMedia(pool, storage, makeFakeLogger(), "bot-1", "MSG1", imageMessage());

    expect(result).toBeNull();
    expect(downloadMediaMessage).not.toHaveBeenCalled();
    expect(storage.put).not.toHaveBeenCalled();
  });

  it("returns null when the CDN download fails, without throwing", async () => {
    vi.mocked(downloadMediaMessage).mockRejectedValue(new Error("network down"));
    const pool = makeFakePool(10_000_000);
    const storage = makeFakeStorage();

    const result = await attachMedia(pool, storage, makeFakeLogger(), "bot-1", "MSG1", imageMessage());

    expect(result).toBeNull();
    expect(storage.put).not.toHaveBeenCalled();
  });

  it("returns null when the storage upload fails, without throwing", async () => {
    vi.mocked(downloadMediaMessage).mockResolvedValue(Buffer.from("bytes"));
    const pool = makeFakePool(10_000_000);
    const storage = { put: vi.fn(async () => { throw new Error("s3 down"); }) };

    const result = await attachMedia(pool, storage, makeFakeLogger(), "bot-1", "MSG1", imageMessage());

    expect(result).toBeNull();
  });

  // Fix 1 (финальный review): wa_msg_id управляется отправляющим клиентом
  // Baileys его не валидирует — без проверки это path traversal в storage key.
  it("returns null and calls neither downloadMediaMessage nor storage.put when wa_msg_id looks like a path traversal", async () => {
    vi.mocked(downloadMediaMessage).mockClear();
    const pool = makeFakePool(10_000_000);
    const storage = makeFakeStorage();

    const result = await attachMedia(
      pool,
      storage,
      makeFakeLogger(),
      "bot-1",
      "../../../../etc/cron.d/evil",
      imageMessage(),
    );

    expect(result).toBeNull();
    expect(downloadMediaMessage).not.toHaveBeenCalled();
    expect(storage.put).not.toHaveBeenCalled();
  });

  // Fix 3 (финальный review): fileLength — заявление отправителя, не факт.
  // Враждебный клиент может занизить его в протобафе и всё равно залить
  // больше байт — downloadMediaMessage буферизует их целиком в памяти.
  it("returns null when the downloaded buffer exceeds the limit even though the reported fileLength did not", async () => {
    const oversized = Buffer.alloc(2_000);
    vi.mocked(downloadMediaMessage).mockResolvedValue(oversized);
    const pool = makeFakePool(1_000); // лимит = 1000 байт
    const storage = makeFakeStorage();
    // Заявленный fileLength (500) в пределах лимита — пре-чек пропускает, но
    // реально скачанное (2000) лимит превышает — должен сработать бэкстоп.
    const msg = imageMessage({ fileLength: 500 });

    const result = await attachMedia(pool, storage, makeFakeLogger(), "bot-1", "MSG1", msg);

    expect(result).toBeNull();
    expect(storage.put).not.toHaveBeenCalled();
  });
});
