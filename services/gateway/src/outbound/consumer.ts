// Consumer group на wa:out: outbound.text / outbound.typing / outbound.image /
// outbound.document / outbound.video -> отправка через Baileys. Идемпотентность
// по client_msg_id (SET NX EX 3600) ДО отправки — ретрай worker'а не должен
// породить дубль сообщения клиенту (CLAUDE.md, "Исходящие идемпотентны").
// Ошибка отправки — до 3 попыток с backoff (см. utils/retry.ts), затем лог +
// ACK без дальнейших ретраев — сообщение теряется, но очередь не блокируется
// навсегда (технический долг, закрыт FEATURES.md 4.3). Обработка entry в
// пачке — по-прежнему последовательная: одна зависшая отправка с ретраями
// (до ~63с в худшем случае) задержит остальные entry той же пачки —
// сознательно принято, распараллеливание пачки — отдельная задача при
// необходимости.
import type { Redis } from "ioredis";

import { Event } from "../contracts/events.js";
import type { SessionManager } from "../session/manager.js";
import type { TransportLogger } from "../logger.js";
import type { Storage } from "../storage/types.js";
import { withRetry } from "../utils/retry.js";
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
    private readonly storage: Storage,
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
      if (
        event.type === "outbound.text" ||
        event.type === "outbound.typing" ||
        event.type === "outbound.image" ||
        event.type === "outbound.document" ||
        event.type === "outbound.video" ||
        event.type === "outbound.reaction"
      ) {
        // Цепочка === (не .includes() на массиве типов) — TS естественно
        // сужает event до нужного Extract-объединения по литералам, без
        // явного as-каста, который потребовался бы при проверке через
        // includes() на readonly-массиве строк.
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
    event: Extract<
      Event,
      {
        type:
          | "outbound.text"
          | "outbound.typing"
          | "outbound.image"
          | "outbound.document"
          | "outbound.video"
          | "outbound.reaction";
      }
    >,
  ): Promise<void> {
    // Формат ключа задокументирован и переиспользуется в libs/core/src/core/redis_keys.py
    // (worker, api) — Блок 3 detect'ит по нему свой echo для handoff. Меняешь тут — меняй и там.
    const dedupeKey = `wa:sent:${event.client_msg_id}`;
    const reserved = await this.redis.set(dedupeKey, "1", "EX", IDEMPOTENCY_TTL_SECONDS, "NX");
    if (reserved !== "OK") {
      this.logger.info({ clientMsgId: event.client_msg_id }, "duplicate client_msg_id, skipping send");
      return;
    }

    try {
      await withRetry(
        async () => {
          if (event.type === "outbound.text") {
            await withTimeout(
              this.sessions.sendText(event.bot_id, event.chat_id, event.text, event.client_msg_id),
              SEND_TIMEOUT_MS,
              "sendText",
            );
          } else if (event.type === "outbound.typing") {
            await withTimeout(
              this.sessions.sendTyping(event.bot_id, event.chat_id),
              SEND_TIMEOUT_MS,
              "sendTyping",
            );
          } else if (event.type === "outbound.image") {
            const image = await withTimeout(
              this.storage.get(event.storage_key),
              SEND_TIMEOUT_MS,
              "storageGet",
            );
            await withTimeout(
              this.sessions.sendImage(event.bot_id, event.chat_id, image, event.mime_type, event.client_msg_id),
              SEND_TIMEOUT_MS,
              "sendImage",
            );
          } else if (event.type === "outbound.document") {
            const document = await withTimeout(
              this.storage.get(event.storage_key),
              SEND_TIMEOUT_MS,
              "storageGet",
            );
            await withTimeout(
              this.sessions.sendDocument(
                event.bot_id, event.chat_id, document, event.mime_type, event.filename, event.client_msg_id,
              ),
              SEND_TIMEOUT_MS,
              "sendDocument",
            );
          } else if (event.type === "outbound.video") {
            const video = await withTimeout(
              this.storage.get(event.storage_key),
              SEND_TIMEOUT_MS,
              "storageGet",
            );
            await withTimeout(
              this.sessions.sendVideo(event.bot_id, event.chat_id, video, event.mime_type, event.client_msg_id),
              SEND_TIMEOUT_MS,
              "sendVideo",
            );
          } else if (event.type === "outbound.reaction") {
            await withTimeout(
              this.sessions.sendReaction(
                event.bot_id, event.chat_id, event.reply_to_wa_msg_id, event.emoji, event.client_msg_id,
              ),
              SEND_TIMEOUT_MS,
              "sendReaction",
            );
          } else {
            // Компилятор ловит здесь любой новый outbound.*-тип, добавленный в
            // контракт (docs/contracts/events.schema.json) без соответствующей
            // ветки выше — раньше был bare else, шестой тип молча утёк бы в
            // video-ветку без ошибки компиляции (найдено ретро-ревью 4.8/4.9).
            const _exhaustive: never = event;
            throw new Error(`unhandled outbound event type: ${JSON.stringify(_exhaustive)}`);
          }
        },
        event.type,
        this.logger,
      );
    } catch (err) {
      this.logger.error(
        { err, botId: event.bot_id, chatId: event.chat_id, clientMsgId: event.client_msg_id },
        "failed to send outbound event",
      );
    }
  }
}
