// Жизненный цикл сессий Baileys: подъём, реконнект с backoff, watchdog,
// QR, явный logout. Ноль бизнес-логики — только транспорт (ADR-002).
import { Boom } from "@hapi/boom";
import makeWASocket, {
  DisconnectReason,
  fetchLatestBaileysVersion,
  jidDecode,
  makeCacheableSignalKeyStore,
  type WASocket,
} from "@whiskeysockets/baileys";
import type { Redis } from "ioredis";
import type { Pool } from "pg";

import type { TransportLogger } from "../logger.js";

import { usePostgresAuthState } from "../auth/postgres-auth-state.js";
import { publishEvent } from "../bus/publish.js";
import type { SessionStatus } from "../contracts/events.js";
import { clearSession, markLinked } from "../db/bots.js";

const RECONNECT_BASE_DELAY_MS = 1_000;
const RECONNECT_MAX_DELAY_MS = 60_000;
const WATCHDOG_INTERVAL_MS = 30_000;
// Без единого события от сокета дольше этого — считаем сессию зависшей и рестартуем.
const WATCHDOG_STALE_MS = 90_000;
const IN_STREAM = "wa:in";

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

  constructor(
    private readonly pool: Pool,
    private readonly redis: Redis,
    private readonly logger: TransportLogger,
  ) {}

  async startAllLinked(botIds: string[]): Promise<void> {
    for (const botId of botIds) {
      await this.startSession(botId);
    }
  }

  /** Идемпотентно: если сессия уже поднята/поднимается — не трогаем её. */
  async startSession(botId: string): Promise<void> {
    if (this.sessions.has(botId)) return;
    await this.connect(botId, 0);
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
    const auth = await usePostgresAuthState(this.pool, botId);
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
      void this.onConnectionUpdate(botId, session, update);
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
        void this.connect(botId, attempt);
      }, delay);
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

  private async publishStatus(botId: string, status: SessionStatus["status"]): Promise<void> {
    const event: SessionStatus = { type: "session.status", bot_id: botId, status, ts: Date.now() };
    try {
      await publishEvent(this.redis, IN_STREAM, event);
    } catch (err) {
      this.logger.error({ err, botId, status }, "failed to publish session.status");
    }
  }
}
