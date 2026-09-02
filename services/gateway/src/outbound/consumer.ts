// Consumer group на wa:out: outbound.text / outbound.typing -> отправка через
// Baileys. Идемпотентность по client_msg_id (SET NX EX 3600) ДО отправки —
// ретрай worker'а не должен породить дубль сообщения клиенту (CLAUDE.md,
// "Исходящие идемпотентны"). Ошибка отправки — лог + ACK, без ретраев
// (ретраи с backoff — Волна 1, вне скоупа Блока 1).
import type { Redis } from "ioredis";

import { Event } from "../contracts/events.js";
import type { SessionManager } from "../session/manager.js";
import type { TransportLogger } from "../logger.js";
import { withTimeout } from "../utils/timeout.js";

const OUT_STREAM = "wa:out";
const GROUP = "gateway";
const IDEMPOTENCY_TTL_SECONDS = 3600;
const BLOCK_MS = 5000;
const BATCH_SIZE = 10;
const SEND_TIMEOUT_MS = 20_000;

type StreamEntry = [id: string, fields: string[]];
type XReadGroupReply = [stream: string, entries: StreamEntry[]][] | null;

function fieldsToPayload(fields: string[]): string | undefined {
  const idx = fields.indexOf("payload");
  return idx >= 0 ? fields[idx + 1] : undefined;
}

export class OutboundConsumer {
  private running = false;
  private loopPromise: Promise<void> | null = null;
  private readonly consumerName = `gateway-${process.pid}`;

  constructor(
    private readonly redis: Redis,
    private readonly sessions: SessionManager,
    private readonly logger: TransportLogger,
  ) {}

  async start(): Promise<void> {
    await this.ensureGroup();
    this.running = true;
    this.loopPromise = this.loop();
  }

  async stop(): Promise<void> {
    this.running = false;
    await this.loopPromise;
  }

  private async ensureGroup(): Promise<void> {
    try {
      await this.redis.xgroup("CREATE", OUT_STREAM, GROUP, "$", "MKSTREAM");
    } catch (err) {
      if (!(err instanceof Error) || !err.message.includes("BUSYGROUP")) throw err;
      // группа уже существует — нормальный случай при рестарте
    }
  }

  private async loop(): Promise<void> {
    while (this.running) {
      let reply: XReadGroupReply;
      try {
        reply = (await this.redis.xreadgroup(
          "GROUP",
          GROUP,
          this.consumerName,
          "COUNT",
          BATCH_SIZE,
          "BLOCK",
          BLOCK_MS,
          "STREAMS",
          OUT_STREAM,
          ">",
        )) as XReadGroupReply;
      } catch (err) {
        this.logger.error({ err }, "xreadgroup failed on wa:out, retrying");
        continue;
      }
      if (!reply) continue; // BLOCK timeout, ничего не пришло

      for (const [, entries] of reply) {
        for (const [id, fields] of entries) {
          await this.processEntry(id, fields);
        }
      }
    }
  }

  private async processEntry(id: string, fields: string[]): Promise<void> {
    const raw = fieldsToPayload(fields);
    try {
      if (!raw) throw new Error("entry has no 'payload' field");
      const event = Event.parse(JSON.parse(raw));
      if (event.type === "outbound.text" || event.type === "outbound.typing") {
        await this.handleOutbound(event);
      } else {
        this.logger.warn({ id, type: event.type }, "unexpected event type on wa:out, skipping");
      }
    } catch (err) {
      this.logger.error({ err, id, raw }, "failed to process wa:out entry, acking anyway");
    } finally {
      await this.redis.xack(OUT_STREAM, GROUP, id);
    }
  }

  private async handleOutbound(
    event: Extract<Event, { type: "outbound.text" | "outbound.typing" }>,
  ): Promise<void> {
    const dedupeKey = `wa:sent:${event.client_msg_id}`;
    const reserved = await this.redis.set(dedupeKey, "1", "EX", IDEMPOTENCY_TTL_SECONDS, "NX");
    if (reserved !== "OK") {
      this.logger.info({ clientMsgId: event.client_msg_id }, "duplicate client_msg_id, skipping send");
      return;
    }

    try {
      if (event.type === "outbound.text") {
        await withTimeout(
          this.sessions.sendText(event.bot_id, event.chat_id, event.text),
          SEND_TIMEOUT_MS,
          "sendText",
        );
      } else {
        await withTimeout(
          this.sessions.sendTyping(event.bot_id, event.chat_id),
          SEND_TIMEOUT_MS,
          "sendTyping",
        );
      }
    } catch (err) {
      this.logger.error(
        { err, botId: event.bot_id, chatId: event.chat_id, clientMsgId: event.client_msg_id },
        "failed to send outbound event",
      );
    }
  }
}
