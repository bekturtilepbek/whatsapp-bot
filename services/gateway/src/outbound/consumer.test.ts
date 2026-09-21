import { describe, expect, it, vi } from "vitest";
import type { Redis } from "ioredis";
import { OutboundConsumer } from "./consumer.js";
import type { SessionManager } from "../session/manager.js";
import type { TransportLogger } from "../logger.js";
import type { Storage } from "../storage/types.js";

const BOT_ID = "00000000-0000-0000-0000-000000000001";

function makeMocks() {
  const dedupeStore = new Set<string>();
  const redis = {
    set: vi.fn(async (...args: unknown[]) => {
      const key = args[0] as string;
      if (dedupeStore.has(key)) return null;
      dedupeStore.add(key);
      return "OK";
    }),
    xack: vi.fn(async () => 1),
  } as unknown as Redis;

  const sessions = {
    sendText: vi.fn(async () => undefined),
    sendTyping: vi.fn(async () => undefined),
    sendImage: vi.fn(async () => undefined),
    sendDocument: vi.fn(async () => undefined),
    sendVideo: vi.fn(async () => undefined),
    sendReaction: vi.fn(async () => undefined),
    sendSeen: vi.fn(async () => undefined),
  } as unknown as SessionManager;

  const logger = {
    level: "info",
    child: () => logger,
    trace: vi.fn(),
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  } as TransportLogger;

  const storage = {
    get: vi.fn(async () => Buffer.from("fake-image-bytes")),
  } as unknown as Storage;

  return { redis, sessions, logger, storage };
}

function payloadFields(payload: unknown): string[] {
  return ["payload", JSON.stringify(payload)];
}

describe("OutboundConsumer idempotency and routing", () => {
  it("sends outbound.text once and reserves the dedupe key", async () => {
    const { redis, sessions, logger, storage } = makeMocks();
    const consumer = new OutboundConsumer(redis, sessions, logger, storage);
    const event = {
      type: "outbound.text",
      bot_id: BOT_ID,
      chat_id: "996700000000@s.whatsapp.net",
      text: "Здравствуйте",
      client_msg_id: "msg-1",
    };

    await (consumer as unknown as { processEntry: (id: string, f: string[]) => Promise<void> })
      .processEntry("1-0", payloadFields(event));

    expect(sessions.sendText).toHaveBeenCalledWith(
      BOT_ID,
      "996700000000@s.whatsapp.net",
      "Здравствуйте",
      "msg-1",
    );
    expect(redis.set).toHaveBeenCalledWith("wa:sent:msg-1", "1", "EX", 3600, "NX");
    expect(redis.xack).toHaveBeenCalledWith("wa:out", "gateway", "1-0");
  });

  it("a failed XACK is logged, not thrown out of processEntry", async () => {
    // Раньше это вылетало бы наружу необработанным — loop() ловит только
    // xreadgroup, и rejected loopPromise никто не await'ит до stop(),
    // роняя весь процесс gateway на первом же сетевом блипе к Redis при ACK.
    const { redis, sessions, logger, storage } = makeMocks();
    (redis.xack as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("simulated redis blip"));
    const consumer = new OutboundConsumer(redis, sessions, logger, storage);
    const event = {
      type: "outbound.text",
      bot_id: BOT_ID,
      chat_id: "996700000000@s.whatsapp.net",
      text: "Здравствуйте",
      client_msg_id: "msg-ack-fail",
    };

    await expect(
      (consumer as unknown as { processEntry: (id: string, f: string[]) => Promise<void> })
        .processEntry("1-0", payloadFields(event)),
    ).resolves.toBeUndefined();

    expect(logger.error).toHaveBeenCalledWith(
      expect.objectContaining({ id: "1-0" }),
      expect.stringContaining("failed to ack wa:out entry"),
    );
  });

  it("skips send on a retried (duplicate) client_msg_id but still ACKs", async () => {
    const { redis, sessions, logger, storage } = makeMocks();
    const consumer = new OutboundConsumer(redis, sessions, logger, storage);
    const event = {
      type: "outbound.text",
      bot_id: BOT_ID,
      chat_id: "996700000000@s.whatsapp.net",
      text: "дубль от ретрая",
      client_msg_id: "msg-dup",
    };
    const entry = (consumer as unknown as { processEntry: (id: string, f: string[]) => Promise<void> })
      .processEntry;

    await entry.call(consumer, "1-0", payloadFields(event));
    await entry.call(consumer, "2-0", payloadFields(event));

    expect(sessions.sendText).toHaveBeenCalledTimes(1);
    expect(redis.xack).toHaveBeenCalledTimes(2); // оба entry подтверждены
  });

  it("routes outbound.typing to sendTyping", async () => {
    const { redis, sessions, logger, storage } = makeMocks();
    const consumer = new OutboundConsumer(redis, sessions, logger, storage);
    const event = {
      type: "outbound.typing",
      bot_id: BOT_ID,
      chat_id: "996700000000@s.whatsapp.net",
      client_msg_id: "typing-1",
    };

    await (consumer as unknown as { processEntry: (id: string, f: string[]) => Promise<void> })
      .processEntry("1-0", payloadFields(event));

    expect(sessions.sendTyping).toHaveBeenCalledWith(BOT_ID, "996700000000@s.whatsapp.net");
    expect(sessions.sendText).not.toHaveBeenCalled();
  });

  it("acks a malformed payload instead of throwing", async () => {
    const { redis, sessions, logger, storage } = makeMocks();
    const consumer = new OutboundConsumer(redis, sessions, logger, storage);

    await expect(
      (consumer as unknown as { processEntry: (id: string, f: string[]) => Promise<void> }).processEntry(
        "1-0",
        ["payload", "{not valid json"],
      ),
    ).resolves.toBeUndefined();

    expect(redis.xack).toHaveBeenCalledWith("wa:out", "gateway", "1-0");
    expect(sessions.sendText).not.toHaveBeenCalled();
  });

  it("retries a transient send failure and succeeds without losing the message", async () => {
    vi.useFakeTimers();
    try {
      const { redis, sessions, logger, storage } = makeMocks();
      (sessions.sendText as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
        new Error("network blip"),
      );
      const consumer = new OutboundConsumer(redis, sessions, logger, storage);
      const event = {
        type: "outbound.text",
        bot_id: BOT_ID,
        chat_id: "996700000000@s.whatsapp.net",
        text: "доставится со второй попытки",
        client_msg_id: "msg-retry",
      };

      const entryPromise = (
        consumer as unknown as { processEntry: (id: string, f: string[]) => Promise<void> }
      ).processEntry("1-0", payloadFields(event));
      await vi.advanceTimersByTimeAsync(1000); // backoff между попыткой 1 и 2
      await entryPromise;

      expect(sessions.sendText).toHaveBeenCalledTimes(2);
      expect(logger.error).not.toHaveBeenCalled();
      expect(redis.xack).toHaveBeenCalledWith("wa:out", "gateway", "1-0");
    } finally {
      vi.useRealTimers();
    }
  });

  it("acks after exhausting all retries on a permanently failing send (FEATURES.md 4.3)", async () => {
    vi.useFakeTimers();
    try {
      const { redis, sessions, logger, storage } = makeMocks();
      (sessions.sendText as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("send failed"));
      const consumer = new OutboundConsumer(redis, sessions, logger, storage);
      const event = {
        type: "outbound.text",
        bot_id: BOT_ID,
        chat_id: "996700000000@s.whatsapp.net",
        text: "не доставится",
        client_msg_id: "msg-fail",
      };

      const entryPromise = (
        consumer as unknown as { processEntry: (id: string, f: string[]) => Promise<void> }
      ).processEntry("1-0", payloadFields(event));
      await vi.advanceTimersByTimeAsync(1000); // между попыткой 1 и 2
      await vi.advanceTimersByTimeAsync(2000); // между попыткой 2 и 3
      await entryPromise;

      expect(sessions.sendText).toHaveBeenCalledTimes(3); // RETRY_MAX_ATTEMPTS
      expect(logger.error).toHaveBeenCalledWith(
        expect.objectContaining({ err: expect.objectContaining({ message: "send failed" }) }),
        "failed to send outbound event",
      );
      expect(redis.xack).toHaveBeenCalledWith("wa:out", "gateway", "1-0");
    } finally {
      vi.useRealTimers();
    }
  });

  it("reads bytes from storage and sends outbound.image via sendImage", async () => {
    const { redis, sessions, logger, storage } = makeMocks();
    const consumer = new OutboundConsumer(redis, sessions, logger, storage);
    const event = {
      type: "outbound.image",
      bot_id: BOT_ID,
      chat_id: "996700000000@s.whatsapp.net",
      storage_key: "bots/bot-1/products/img-1.jpg",
      mime_type: "image/jpeg",
      client_msg_id: "img-1",
    };

    await (consumer as unknown as { processEntry: (id: string, f: string[]) => Promise<void> })
      .processEntry("1-0", payloadFields(event));

    expect(storage.get).toHaveBeenCalledWith("bots/bot-1/products/img-1.jpg");
    expect(sessions.sendImage).toHaveBeenCalledWith(
      BOT_ID,
      "996700000000@s.whatsapp.net",
      Buffer.from("fake-image-bytes"),
      "image/jpeg",
      "img-1",
    );
    expect(redis.set).toHaveBeenCalledWith("wa:sent:img-1", "1", "EX", 3600, "NX");
    expect(redis.xack).toHaveBeenCalledWith("wa:out", "gateway", "1-0");
  });

  it("bounds a hanging storage.get with the send timeout on every retry attempt, then gives up", async () => {
    vi.useFakeTimers();
    try {
      const { redis, sessions, logger, storage } = makeMocks();
      // storage.get никогда не резолвится ни на одной попытке — имитация
      // зависшего S3/диска, не единичного сетевого сбоя.
      (storage.get as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}));
      const consumer = new OutboundConsumer(redis, sessions, logger, storage);
      const event = {
        type: "outbound.image",
        bot_id: BOT_ID,
        chat_id: "996700000000@s.whatsapp.net",
        storage_key: "bots/bot-1/products/img-hang.jpg",
        mime_type: "image/jpeg",
        client_msg_id: "img-hang",
      };

      const entryPromise = (
        consumer as unknown as { processEntry: (id: string, f: string[]) => Promise<void> }
      ).processEntry("1-0", payloadFields(event));

      // Каждая попытка сама по себе ограничена SEND_TIMEOUT_MS (20с);
      // withRetry добавляет backoff (1с, 2с) между тремя попытками —
      // итого 20с+1с+20с+2с+20с прежде чем сдаться.
      await vi.advanceTimersByTimeAsync(20_000);
      await vi.advanceTimersByTimeAsync(1_000);
      await vi.advanceTimersByTimeAsync(20_000);
      await vi.advanceTimersByTimeAsync(2_000);
      await vi.advanceTimersByTimeAsync(20_000);
      await entryPromise;

      expect(sessions.sendImage).not.toHaveBeenCalled();
      expect(storage.get).toHaveBeenCalledTimes(3); // RETRY_MAX_ATTEMPTS
      expect(logger.error).toHaveBeenCalledWith(
        expect.objectContaining({
          err: expect.objectContaining({ message: "storageGet timed out after 20000ms" }),
        }),
        "failed to send outbound event",
      );
      // ACK всё равно происходит — зависший storage не должен вешать очередь остальным ботам
      expect(redis.xack).toHaveBeenCalledWith("wa:out", "gateway", "1-0");
    } finally {
      vi.useRealTimers();
    }
  });

  it("skips a duplicate outbound.image client_msg_id but still ACKs", async () => {
    const { redis, sessions, logger, storage } = makeMocks();
    const consumer = new OutboundConsumer(redis, sessions, logger, storage);
    const event = {
      type: "outbound.image",
      bot_id: BOT_ID,
      chat_id: "996700000000@s.whatsapp.net",
      storage_key: "bots/bot-1/products/img-1.jpg",
      mime_type: "image/jpeg",
      client_msg_id: "img-dup",
    };
    const entry = (consumer as unknown as { processEntry: (id: string, f: string[]) => Promise<void> })
      .processEntry;

    await entry.call(consumer, "1-0", payloadFields(event));
    await entry.call(consumer, "2-0", payloadFields(event));

    expect(sessions.sendImage).toHaveBeenCalledTimes(1);
  });

  it("reads bytes from storage and sends outbound.document via sendDocument with filename", async () => {
    const { redis, sessions, logger, storage } = makeMocks();
    const consumer = new OutboundConsumer(redis, sessions, logger, storage);
    const event = {
      type: "outbound.document",
      bot_id: BOT_ID,
      chat_id: "996700000000@s.whatsapp.net",
      storage_key: "bots/bot-1/documents/price-list.pdf",
      mime_type: "application/pdf",
      filename: "price-list.pdf",
      client_msg_id: "doc-1",
    };

    await (consumer as unknown as { processEntry: (id: string, f: string[]) => Promise<void> })
      .processEntry("1-0", payloadFields(event));

    expect(storage.get).toHaveBeenCalledWith("bots/bot-1/documents/price-list.pdf");
    expect(sessions.sendDocument).toHaveBeenCalledWith(
      BOT_ID,
      "996700000000@s.whatsapp.net",
      Buffer.from("fake-image-bytes"),
      "application/pdf",
      "price-list.pdf",
      "doc-1",
    );
    expect(redis.xack).toHaveBeenCalledWith("wa:out", "gateway", "1-0");
  });

  it("reads bytes from storage and sends outbound.video via sendVideo", async () => {
    const { redis, sessions, logger, storage } = makeMocks();
    const consumer = new OutboundConsumer(redis, sessions, logger, storage);
    const event = {
      type: "outbound.video",
      bot_id: BOT_ID,
      chat_id: "996700000000@s.whatsapp.net",
      storage_key: "bots/bot-1/documents/tour.mp4",
      mime_type: "video/mp4",
      client_msg_id: "video-1",
    };

    await (consumer as unknown as { processEntry: (id: string, f: string[]) => Promise<void> })
      .processEntry("1-0", payloadFields(event));

    expect(storage.get).toHaveBeenCalledWith("bots/bot-1/documents/tour.mp4");
    expect(sessions.sendVideo).toHaveBeenCalledWith(
      BOT_ID,
      "996700000000@s.whatsapp.net",
      Buffer.from("fake-image-bytes"),
      "video/mp4",
      "video-1",
    );
    expect(redis.xack).toHaveBeenCalledWith("wa:out", "gateway", "1-0");
  });

  it("routes outbound.reaction to sendReaction (FEATURES.md 9.10)", async () => {
    const { redis, sessions, logger, storage } = makeMocks();
    const consumer = new OutboundConsumer(redis, sessions, logger, storage);
    const event = {
      type: "outbound.reaction",
      bot_id: BOT_ID,
      chat_id: "996700000000@s.whatsapp.net",
      reply_to_wa_msg_id: "3EB0C767D82A1B0C4A5F",
      emoji: "👍",
      client_msg_id: "reaction-1",
    };

    await (consumer as unknown as { processEntry: (id: string, f: string[]) => Promise<void> })
      .processEntry("1-0", payloadFields(event));

    expect(sessions.sendReaction).toHaveBeenCalledWith(
      BOT_ID,
      "996700000000@s.whatsapp.net",
      "3EB0C767D82A1B0C4A5F",
      "👍",
      "reaction-1",
    );
    expect(redis.set).toHaveBeenCalledWith("wa:sent:reaction-1", "1", "EX", 3600, "NX");
    expect(redis.xack).toHaveBeenCalledWith("wa:out", "gateway", "1-0");
  });

  it("skips a duplicate outbound.reaction client_msg_id but still ACKs", async () => {
    const { redis, sessions, logger, storage } = makeMocks();
    const consumer = new OutboundConsumer(redis, sessions, logger, storage);
    const event = {
      type: "outbound.reaction",
      bot_id: BOT_ID,
      chat_id: "996700000000@s.whatsapp.net",
      reply_to_wa_msg_id: "3EB0C767D82A1B0C4A5F",
      emoji: "👍",
      client_msg_id: "reaction-dup",
    };
    const entry = (consumer as unknown as { processEntry: (id: string, f: string[]) => Promise<void> })
      .processEntry;

    await entry.call(consumer, "1-0", payloadFields(event));
    await entry.call(consumer, "2-0", payloadFields(event));

    expect(sessions.sendReaction).toHaveBeenCalledTimes(1);
    expect(redis.xack).toHaveBeenCalledTimes(2);
  });

  it("routes outbound.seen to sendSeen (FEATURES.md 1.11)", async () => {
    const { redis, sessions, logger, storage } = makeMocks();
    const consumer = new OutboundConsumer(redis, sessions, logger, storage);
    const event = {
      type: "outbound.seen",
      bot_id: BOT_ID,
      chat_id: "996700000000@s.whatsapp.net",
      wa_msg_id: "3EB0C767D82A1B0C4A5F",
      client_msg_id: "seen-1",
    };

    await (consumer as unknown as { processEntry: (id: string, f: string[]) => Promise<void> })
      .processEntry("1-0", payloadFields(event));

    expect(sessions.sendSeen).toHaveBeenCalledWith(
      BOT_ID,
      "996700000000@s.whatsapp.net",
      "3EB0C767D82A1B0C4A5F",
    );
    expect(redis.set).toHaveBeenCalledWith("wa:sent:seen-1", "1", "EX", 3600, "NX");
    expect(redis.xack).toHaveBeenCalledWith("wa:out", "gateway", "1-0");
  });

  it("skips a duplicate outbound.seen client_msg_id but still ACKs", async () => {
    const { redis, sessions, logger, storage } = makeMocks();
    const consumer = new OutboundConsumer(redis, sessions, logger, storage);
    const event = {
      type: "outbound.seen",
      bot_id: BOT_ID,
      chat_id: "996700000000@s.whatsapp.net",
      wa_msg_id: "3EB0C767D82A1B0C4A5F",
      client_msg_id: "seen-dup",
    };
    const entry = (consumer as unknown as { processEntry: (id: string, f: string[]) => Promise<void> })
      .processEntry;

    await entry.call(consumer, "1-0", payloadFields(event));
    await entry.call(consumer, "2-0", payloadFields(event));

    expect(sessions.sendSeen).toHaveBeenCalledTimes(1);
    expect(redis.xack).toHaveBeenCalledTimes(2);
  });
});
