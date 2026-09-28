// Жизненный цикл сессий Baileys: подъём, реконнект с backoff, watchdog,
// QR, явный logout. Ноль бизнес-логики — только транспорт (ADR-002).
import { Boom } from "@hapi/boom";
import makeWASocket, {
  DisconnectReason,
  fetchLatestBaileysVersion,
  jidDecode,
  makeCacheableSignalKeyStore,
  type MessageUpsertType,
  type WAMessage,
  type WASocket,
} from "@whiskeysockets/baileys";
import type { Redis } from "ioredis";
import type { Pool } from "pg";
import sharp from "sharp";

import type { TransportLogger } from "../logger.js";

import { usePostgresAuthState } from "../auth/postgres-auth-state.js";
import { publishEvent } from "../bus/publish.js";
import type { InboundText, SessionStatus } from "../contracts/events.js";
import { clearSession, markLinked, setSessionStatus } from "../db/bots.js";
import { attachMedia } from "../media/download.js";
import { normalizeInboundMessage } from "../normalize/inbound.js";
import type { Storage } from "../storage/types.js";

const RECONNECT_BASE_DELAY_MS = 1_000;
const RECONNECT_MAX_DELAY_MS = 60_000;
const WATCHDOG_INTERVAL_MS = 30_000;
// Backstop, не основная защита: реальный обрыв связи Baileys сам обнаруживает
// через собственный keepalive к серверам WA и эмитит connection.update(close)
// (уже обновляет lastActivity ниже) — onConnectionUpdate реконнектит по этому
// сигналу независимо от watchdog. Этот таймер нужен только на случай, если
// САМ Baileys не заметил свою смерть (завис изнутри, событие не долетело) —
// такое реже, чем просто тихая переписка. Раньше здесь стояло 90с — это
// ловило не зависшие сокеты, а любого бота, которому никто не писал 90с:
// watchdog путал тишину клиентов с смертью сокета и рвал полностью рабочие
// сессии каждые ~2 минуты (найдено живьём 2026-09-19, идентичный цикл
// open→~90с тишины→forcing reconnect в логах). Порог сильно увеличен, чтобы
// не путать обычную паузу в переписке с реальным зависанием.
const WATCHDOG_STALE_MS = 15 * 60_000;
const IN_STREAM = "wa:in";

/**
 * Fix 2 (финальный review): не скачиваем/не заливаем медиа, которое worker
 * всё равно отбросит до сохранения — группы и status@broadcast worker
 * игнорирует целиком (см. is_ignored_chat в
 * services/worker/src/worker/pipeline/filters.py), а from_me-сообщения
 * попадают не в insert_incoming, а в отдельный путь handoff-детекта
 * (_handle_manager_message/insert_outgoing), который media_ref не использует.
 * Скачивание для них — трата и (для from_me) задержка детекта handoff.
 */
function isMediaDownloadSkipped(event: InboundText): boolean {
  return event.from_me || event.chat_id.endsWith("@g.us") || event.chat_id === "status@broadcast";
}

const IMAGE_THUMBNAIL_WIDTH = 32;

/**
 * Baileys сам умеет генерировать превью (jpegThumbnail) для outbound-фото —
 * но делает это, читая ОРИГИНАЛЬНЫЙ файл, который сам же асинхронно пишет на
 * диск (encryptedStream → originalFileStream.end(), без ожидания реального
 * flush) ПАРАЛЛЕЛЬНО с чтением этого же файла для превью (Promise.all) —
 * гонка внутри самой библиотеки. Живая проверка 2026-09-22: воспроизводится
 * стабильно (2/2) на реальном фото товара — Sharp падает с "Input file
 * contains unsupported image format" (усечённый на середине записи файл),
 * само фото при этом доставляется, просто без превью. Обходим: генерируем
 * превью сами из буфера, который уже целиком в памяти (гонки быть не может),
 * и передаём готовым — Baileys не лезет генерировать его сам
 * (generateThumbnail пропускается, если jpegThumbnail уже задан).
 */
async function buildJpegThumbnail(image: Buffer, logger: TransportLogger): Promise<string | undefined> {
  try {
    const buf = await sharp(image).resize(IMAGE_THUMBNAIL_WIDTH).jpeg({ quality: 50 }).toBuffer();
    return buf.toString("base64");
  } catch (err) {
    logger.warn({ err }, "failed to build jpeg thumbnail, sending without preview");
    return undefined;
  }
}

interface RunningSession {
  sock: WASocket;
  latestQr: string | null;
  qrWaiters: Array<(qr: string) => void>;
  reconnectAttempts: number;
  lastActivity: number;
  watchdogTimer: ReturnType<typeof setInterval>;
  disposeAuth: () => Promise<void>;
  stopping: boolean;
}

export class SessionManager {
  private readonly sessions = new Map<string, RunningSession>();
  // Хвост цепочки записей статуса per bot — см. publishStatus() ниже.
  private readonly statusWriteChains = new Map<string, Promise<void>>();
  // connect() в процессе, до того как сессия попадёт в this.sessions — см.
  // startSession() ниже.
  private readonly connecting = new Map<string, Promise<void>>();

  constructor(
    private readonly pool: Pool,
    private readonly redis: Redis,
    private readonly logger: TransportLogger,
    private readonly storage: Storage,
  ) {}

  async startAllLinked(botIds: string[]): Promise<void> {
    for (const botId of botIds) {
      await this.startSession(botId);
    }
  }

  /**
   * Идемпотентно: если сессия уже поднята/поднимается — не трогаем её.
   *
   * Живой баг (security review, 2026-09-28): `connect()` делает два await
   * (чтение auth-state из Postgres, запрос версии Baileys) ДО того, как
   * сессия попадает в `this.sessions` — раньше проверка `sessions.has()`
   * выше была единственной защитой, и два близких по времени вызова (два
   * `/qr/:botId` подряд, дабл-клик, поллинг дашборда) оба проходили её до
   * того, как первый успевал дойти до `sessions.set`. Второй `connect()`
   * тогда перезаписывал запись в Map, а первый сокет оставался осиротевшим:
   * его watchdog-таймер никогда не чистился (утечка), его слушатели
   * продолжали публиковать КАЖДОЕ входящее сообщение в wa:in ДВАЖДЫ, и
   * WhatsApp рано или поздно закрывал один из двух сокетов через
   * connectionReplaced — что не является loggedOut и уходит в обычный
   * реконнект, порождая бесконечный цикл замены. Резервируем слот
   * СИНХРОННО (до первого await), чтобы конкурентный вызов увидел уже
   * идущий connect() и дождался именно его, а не запустил второй.
   */
  async startSession(botId: string): Promise<void> {
    if (this.sessions.has(botId)) return;
    const inFlight = this.connecting.get(botId);
    if (inFlight) {
      await inFlight;
      return;
    }
    const attempt = this.connect(botId, 0).finally(() => {
      this.connecting.delete(botId);
    });
    this.connecting.set(botId, attempt);
    await attempt;
  }

  /** Отдаёт ближайший QR для бота, поднимая сессию при первой привязке. */
  async waitForQr(botId: string, timeoutMs = 20_000): Promise<string> {
    await this.startSession(botId);
    const session = this.sessions.get(botId);
    if (!session) throw new Error("session failed to start");
    if (session.latestQr) return session.latestQr;

    return new Promise<string>((resolve, reject) => {
      const timer = setTimeout(() => {
        const idx = session.qrWaiters.indexOf(onQr);
        if (idx >= 0) session.qrWaiters.splice(idx, 1);
        reject(new Error("qr timeout"));
      }, timeoutMs);
      const onQr = (qr: string): void => {
        clearTimeout(timer);
        resolve(qr);
      };
      session.qrWaiters.push(onQr);
    });
  }

  /** Единственный способ разорвать сессию — явный logout (правило проекта). */
  async logout(botId: string): Promise<void> {
    const session = this.sessions.get(botId);
    if (session) {
      session.stopping = true;
      clearInterval(session.watchdogTimer);
      this.sessions.delete(botId);
      try {
        await session.sock.logout();
      } catch (err) {
        this.logger.warn({ err, botId }, "logout call failed, clearing session state anyway");
      }
      await session.disposeAuth();
    }
    await clearSession(this.pool, botId);
  }

  /** Активный ли сокет у бота прямо сейчас (не reconnecting-плейсхолдер). */
  private activeSocket(botId: string): WASocket {
    const session = this.sessions.get(botId);
    if (!session) throw new Error(`no session running for bot ${botId}`);
    return session.sock;
  }

  /**
   * messageId = clientMsgId — не просто трассировка: Блок 3 (handoff)
   * различает наш echo от ручного ответа менеджера именно по тому, что
   * wa_msg_id пришедшего from_me-сообщения совпадает с client_msg_id,
   * который мы сами выдали при отправке (см. wa:sent:{client_msg_id} —
   * тот же ключ идемпотентности снизу).
   */
  async sendText(botId: string, chatId: string, text: string, clientMsgId: string): Promise<void> {
    await this.activeSocket(botId).sendMessage(chatId, { text }, { messageId: clientMsgId });
  }

  async sendTyping(botId: string, chatId: string): Promise<void> {
    await this.activeSocket(botId).sendPresenceUpdate("composing", chatId);
  }

  /** Синие галочки клиенту (NEW — не было в V1, см. FEATURES.md 1.11).
   * key.fromMe:false — отмечаем ЕГО сообщение прочитанным, не своё
   * (симметрично sendReaction ниже). readMessages не отправляет отдельное
   * сообщение — client_msg_id у outbound.seen нужен только на уровне
   * OutboundConsumer (идемпотентность wa:sent:*), самому Baileys-вызову
   * не передаётся, messageId у него нет. */
  async sendSeen(botId: string, chatId: string, waMsgId: string): Promise<void> {
    await this.activeSocket(botId).readMessages([{ remoteJid: chatId, id: waMsgId, fromMe: false }]);
  }

  /** Реакция-эмодзи на сообщение клиента (FEATURES.md 9.10) — key.fromMe:false,
   * реагируем на ЕГО сообщение, не на своё. Живьём проверено на реальном
   * номере (спайк 2026-09-12): реакция доставляется и отображается. */
  async sendReaction(
    botId: string,
    chatId: string,
    replyToWaMsgId: string,
    emoji: string,
    clientMsgId: string,
  ): Promise<void> {
    await this.activeSocket(botId).sendMessage(
      chatId,
      { react: { text: emoji, key: { remoteJid: chatId, id: replyToWaMsgId, fromMe: false } } },
      { messageId: clientMsgId },
    );
  }

  /** Аналогично sendText — messageId=clientMsgId для той же связки с
   * идемпотентностью/handoff-echo-детектом (wa:sent:{client_msg_id}). */
  async sendImage(
    botId: string,
    chatId: string,
    image: Buffer,
    mimeType: string,
    clientMsgId: string,
  ): Promise<void> {
    const jpegThumbnail = await buildJpegThumbnail(image, this.logger);
    await this.activeSocket(botId).sendMessage(
      chatId,
      { image, mimetype: mimeType, ...(jpegThumbnail ? { jpegThumbnail } : {}) },
      { messageId: clientMsgId },
    );
  }

  /** Аналогично sendImage — messageId=clientMsgId, плюс fileName: Baileys
   * (и сам WhatsApp) требует его, иначе клиент не увидит имя файла. */
  async sendDocument(
    botId: string,
    chatId: string,
    document: Buffer,
    mimeType: string,
    filename: string,
    clientMsgId: string,
  ): Promise<void> {
    await this.activeSocket(botId).sendMessage(
      chatId,
      { document, mimetype: mimeType, fileName: filename },
      { messageId: clientMsgId },
    );
  }

  /** Аналогично sendImage — нативное video-сообщение (плеер в чате),
   * fileName не нужен. */
  async sendVideo(
    botId: string,
    chatId: string,
    video: Buffer,
    mimeType: string,
    clientMsgId: string,
  ): Promise<void> {
    await this.activeSocket(botId).sendMessage(
      chatId,
      { video, mimetype: mimeType },
      { messageId: clientMsgId },
    );
  }

  async stopAll(): Promise<void> {
    for (const [botId, session] of this.sessions) {
      session.stopping = true;
      clearInterval(session.watchdogTimer);
      session.sock.end(undefined);
      await session.disposeAuth();
      this.logger.info({ botId }, "session stopped for shutdown");
    }
    this.sessions.clear();
  }

  private async connect(botId: string, attempt: number): Promise<void> {
    const auth = await usePostgresAuthState(this.pool, botId, this.logger);
    const { version } = await fetchLatestBaileysVersion().catch(() => ({ version: undefined }));

    const sock = makeWASocket({
      auth: {
        creds: auth.state.creds,
        keys: makeCacheableSignalKeyStore(auth.state.keys, this.logger),
      },
      version,
      logger: this.logger.child({ botId }),
      syncFullHistory: false,
      markOnlineOnConnect: false,
    });

    const session: RunningSession = {
      sock,
      latestQr: null,
      qrWaiters: [],
      reconnectAttempts: attempt,
      lastActivity: Date.now(),
      disposeAuth: auth.dispose,
      stopping: false,
      watchdogTimer: setInterval(() => this.checkWatchdog(botId), WATCHDOG_INTERVAL_MS),
    };
    this.sessions.set(botId, session);

    sock.ev.on("creds.update", auth.saveCreds);
    sock.ev.on("connection.update", (update) => {
      session.lastActivity = Date.now();
      // markLinked/clearSession внутри onConnectionUpdate бьют в Postgres
      // без своего try/catch — необработанный reject здесь становится
      // unhandledRejection и роняет ВЕСЬ процесс gateway (обрывая сессии
      // ВСЕХ ботов на узле, не только этого), тот же класс бага, что уже
      // нашли и закрыли в pool.ts/redis.ts (security review, 2026-09-28).
      this.onConnectionUpdate(botId, session, update).catch((err) => {
        this.logger.error({ err, botId }, "onConnectionUpdate failed");
      });
    });
    sock.ev.on("messages.upsert", (upsert) => {
      session.lastActivity = Date.now();
      void this.onMessagesUpsert(botId, upsert);
    });

    await this.publishStatus(botId, "connecting");
  }

  private async onConnectionUpdate(
    botId: string,
    session: RunningSession,
    update: Partial<{
      connection: "open" | "connecting" | "close";
      qr?: string;
      lastDisconnect?: { error: Error | Boom | undefined };
    }>,
  ): Promise<void> {
    if (update.qr) {
      session.latestQr = update.qr;
      const waiters = session.qrWaiters.splice(0, session.qrWaiters.length);
      for (const resolve of waiters) resolve(update.qr);
      await this.publishStatus(botId, "qr");
      return;
    }

    if (update.connection === "open") {
      session.reconnectAttempts = 0;
      session.latestQr = null;
      const decoded = jidDecode(session.sock.user?.id);
      await markLinked(this.pool, botId, decoded?.user);
      await this.publishStatus(botId, "open");
      return;
    }

    if (update.connection === "close") {
      if (session.stopping) return;

      const statusCode = (update.lastDisconnect?.error as Boom | undefined)?.output?.statusCode;
      const loggedOut = statusCode === DisconnectReason.loggedOut;

      if (loggedOut) {
        this.logger.warn({ botId }, "session logged out remotely, clearing");
        clearInterval(session.watchdogTimer);
        this.sessions.delete(botId);
        await clearSession(this.pool, botId);
        await this.publishStatus(botId, "logged_out");
        return;
      }

      // Запись в sessions НЕ удаляем: до фактического реконнекта она служит
      // плейсхолдером, чтобы startSession/waitForQr не подняли второй сокет
      // на того же бота параллельно с ожиданием backoff. connect() ниже
      // заменит её новым RunningSession через this.sessions.set(...).
      clearInterval(session.watchdogTimer);
      const attempt = session.reconnectAttempts + 1;
      const delay = Math.min(RECONNECT_BASE_DELAY_MS * 2 ** session.reconnectAttempts, RECONNECT_MAX_DELAY_MS);
      this.logger.warn({ botId, attempt, delay }, "session closed, reconnecting");
      await this.publishStatus(botId, "reconnecting");
      setTimeout(() => {
        // connect() бьёт в Postgres (auth-state) и делает сетевой запрос
        // (fetchLatestBaileysVersion) до какого-либо try/catch у вызывающего
        // кода — необработанный reject тут тоже unhandledRejection, тот же
        // класс бага, что и у onConnectionUpdate выше. Дополнительно: если
        // connect() падает ДО своего sessions.set (см. комментарий выше —
        // старая запись-плейсхолдер намеренно не удаляется до replace), эта
        // устаревшая запись иначе осталась бы в this.sessions НАВСЕГДА —
        // sessions.has(botId) продолжал бы быть true, и startSession/
        // waitForQr больше никогда не подняли бы сессию заново без рестарта
        // всего gateway. Чистим её сами при неудаче, чтобы бот оставался
        // восстановимым обычным путём (следующий /qr).
        this.connect(botId, attempt).catch((err) => {
          this.logger.error({ err, botId, attempt }, "scheduled reconnect failed");
          if (this.sessions.get(botId) === session) {
            this.sessions.delete(botId);
          }
        });
      }, delay);
    }
  }

  private async onMessagesUpsert(
    botId: string,
    upsert: { messages: WAMessage[]; type: MessageUpsertType },
  ): Promise<void> {
    // "append" — доливка истории при синке/реконнекте, а не живое сообщение;
    // в Блок 1 не публикуем, иначе на каждый реконнект в wa:in льётся история.
    if (upsert.type !== "notify") return;

    for (const msg of upsert.messages) {
      const event = normalizeInboundMessage(botId, msg);
      if (!event) continue;

      let outgoingEvent = event;
      if (event.media_type && !isMediaDownloadSkipped(event)) {
        const attachment = await attachMedia(this.pool, this.storage, this.logger, botId, event.wa_msg_id, msg);
        if (attachment) {
          outgoingEvent = { ...event, ...attachment };
        }
      }

      try {
        await publishEvent(this.redis, IN_STREAM, outgoingEvent);
      } catch (err) {
        this.logger.error({ err, botId, waMsgId: event.wa_msg_id }, "failed to publish inbound.text");
      }
    }
  }

  /** Сокет не присылал вообще никаких обновлений слишком долго — форсируем рестарт. */
  private checkWatchdog(botId: string): void {
    const session = this.sessions.get(botId);
    if (!session || session.stopping) return;
    const idleMs = Date.now() - session.lastActivity;
    if (idleMs > WATCHDOG_STALE_MS) {
      this.logger.warn({ botId, idleMs }, "watchdog: session stale, forcing reconnect");
      session.sock.end(new Error("watchdog: no activity"));
    }
  }

  /**
   * Публикует событие в поток (пайплайн диалога его дропает, см. consumer.py)
   * И пишет статус напрямую в Postgres (ADR-006) — единственный способ
   * дашборду (FEATURES.md 6.17) узнать текущее состояние сессии, раз
   * событие само по себе нигде не оседает.
   *
   * Живой баг (2026-09-28): connect() зовёт publishStatus("connecting")
   * ПОСЛЕ регистрации слушателя connection.update — если реальный хендшейк
   * Baileys (обычно ~1-2с) завершается, пока ЕЩЁ не отрезолвился запрос
   * "connecting" (например, из-за очереди в пуле Postgres сразу после
   * рестарта gateway), два независимых pool.query() гоняются без всякой
   * синхронизации между собой: чей ответ от Postgres придёт позже — тот и
   * победит в UPSERT, независимо от порядка ВЫЗОВА publishStatus. На живом
   * стенде это откатило статус реально открытого, рабочего соединения
   * обратно на "connecting" — бот отвечал в WhatsApp, а бейдж в кабинете
   * показывал "не подключён" бессрочно (сам open→connection.update больше
   * не повторится, пока не будет следующего реконнекта). Фикс — цепочка
   * промисов per bot: запись всегда применяется к Postgres в том порядке,
   * в котором publishStatus была ВЫЗВАНА, а не в порядке, в котором успел
   * ответить пул. Redis-публикацию (ниже) не трогаем — она best-effort,
   * само событие worker дропает (см. consumer.py), только для дашборда.
   */
  private async publishStatus(botId: string, status: SessionStatus["status"]): Promise<void> {
    const event: SessionStatus = { type: "session.status", bot_id: botId, status, ts: Date.now() };
    try {
      await publishEvent(this.redis, IN_STREAM, event);
    } catch (err) {
      this.logger.error({ err, botId, status }, "failed to publish session.status");
    }
    const previous = this.statusWriteChains.get(botId) ?? Promise.resolve();
    const next = previous.then(async () => {
      try {
        await setSessionStatus(this.pool, botId, status);
      } catch (err) {
        this.logger.error({ err, botId, status }, "failed to persist session status");
      }
    });
    this.statusWriteChains.set(botId, next);
    await next;
  }
}
