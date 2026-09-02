import { describe, expect, it, vi } from "vitest";
import type { Redis } from "ioredis";
import { OutboundConsumer } from "./consumer.js";
import type { SessionManager } from "../session/manager.js";
import type { TransportLogger } from "../logger.js";

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

  return { redis, sessions, logger };
}

function payloadFields(payload: unknown): string[] {
  return ["payload", JSON.stringify(payload)];
}

describe("OutboundConsumer idempotency and routing", () => {
  it("sends outbound.text once and reserves the dedupe key", async () => {
    const { redis, sessions, logger } = makeMocks();
    const consumer = new OutboundConsumer(redis, sessions, logger);
    const event = {
      type: "outbound.text",
      bot_id: BOT_ID,
      chat_id: "996700000000@s.whatsapp.net",
      text: "Здравствуйте",
      client_msg_id: "msg-1",
    };

    await (consumer as unknown as { processEntry: (id: string, f: string[]) => Promise<void> })
      .processEntry("1-0", payloadFields(event));

    expect(sessions.sendText).toHaveBeenCalledWith(BOT_ID, "996700000000@s.whatsapp.net", "Здравствуйте");
    expect(redis.set).toHaveBeenCalledWith("wa:sent:msg-1", "1", "EX", 3600, "NX");
    expect(redis.xack).toHaveBeenCalledWith("wa:out", "gateway", "1-0");
  });

  it("skips send on a retried (duplicate) client_msg_id but still ACKs", async () => {
    const { redis, sessions, logger } = makeMocks();
    const consumer = new OutboundConsumer(redis, sessions, logger);
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
    const { redis, sessions, logger } = makeMocks();
    const consumer = new OutboundConsumer(redis, sessions, logger);
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
    const { redis, sessions, logger } = makeMocks();
    const consumer = new OutboundConsumer(redis, sessions, logger);

    await expect(
      (consumer as unknown as { processEntry: (id: string, f: string[]) => Promise<void> }).processEntry(
        "1-0",
        ["payload", "{not valid json"],
      ),
    ).resolves.toBeUndefined();

    expect(redis.xack).toHaveBeenCalledWith("wa:out", "gateway", "1-0");
    expect(sessions.sendText).not.toHaveBeenCalled();
  });

  it("acks even when the send itself fails", async () => {
    const { redis, sessions, logger } = makeMocks();
    (sessions.sendText as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error("send failed"));
    const consumer = new OutboundConsumer(redis, sessions, logger);
    const event = {
      type: "outbound.text",
      bot_id: BOT_ID,
      chat_id: "996700000000@s.whatsapp.net",
      text: "не доставится",
      client_msg_id: "msg-fail",
    };

    await (consumer as unknown as { processEntry: (id: string, f: string[]) => Promise<void> })
      .processEntry("1-0", payloadFields(event));

    expect(redis.xack).toHaveBeenCalledWith("wa:out", "gateway", "1-0");
  });
});
