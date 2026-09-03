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
});
