// Auth-state сессии Baileys — в Postgres, не в памяти процесса (ADR-006).
//
// bot_sessions.auth_state хранит ОДИН JSONB-блок { creds, keys }. Сессия у бота
// в любой момент времени поднята ровно в одном процессе gateway, поэтому
// конкурентной записи в одну строку нет — можно держать состояние целиком
// в памяти и перезаписывать столбец целиком при каждом flush, без jsonb_set.
//
// creds.update пишется в БД немедленно (await до возврата из saveCreds) —
// падение процесса не должно терять обновление creds. Операции над
// signal-keys (session/pre-key/sender-key...) идут пачками и часто — их
// пишем с debounce, чтобы не бить Postgres на каждый вызов set().
import type { Pool } from "pg";
import type {
  AuthenticationCreds,
  AuthenticationState,
  SignalDataSet,
  SignalDataTypeMap,
} from "@whiskeysockets/baileys";
import { BufferJSON, initAuthCreds } from "@whiskeysockets/baileys";

import type { TransportLogger } from "../logger.js";

type KeysByType = { [T in keyof SignalDataTypeMap]?: Record<string, SignalDataTypeMap[T]> };

interface StoredAuthState {
  creds: AuthenticationCreds;
  keys: KeysByType;
}

const KEYS_FLUSH_DEBOUNCE_MS = 1000;

function serialize(value: unknown): string {
  return JSON.stringify(value, BufferJSON.replacer);
}

function deserialize<T>(json: string): T {
  return JSON.parse(json, BufferJSON.reviver) as T;
}

async function loadStoredState(pool: Pool, botId: string): Promise<StoredAuthState> {
  const { rows } = await pool.query<{ auth_state_text: string | null }>(
    "SELECT auth_state::text AS auth_state_text FROM bot_sessions WHERE bot_id = $1",
    [botId],
  );
  const text = rows[0]?.auth_state_text;
  if (!text || text === "{}") {
    return { creds: initAuthCreds(), keys: {} };
  }
  const parsed = deserialize<Partial<StoredAuthState>>(text);
  return { creds: parsed.creds ?? initAuthCreds(), keys: parsed.keys ?? {} };
}

async function persist(pool: Pool, botId: string, state: StoredAuthState): Promise<void> {
  await pool.query(
    `INSERT INTO bot_sessions (bot_id, auth_state)
     VALUES ($1, $2::jsonb)
     ON CONFLICT (bot_id) DO UPDATE SET auth_state = EXCLUDED.auth_state`,
    [botId, serialize(state)],
  );
}

export interface PostgresAuthState {
  state: AuthenticationState;
  saveCreds: () => Promise<void>;
  /** Останавливает debounce-таймер и синхронно сбрасывает несохранённые ключи. */
  dispose: () => Promise<void>;
}

export async function usePostgresAuthState(
  pool: Pool,
  botId: string,
  logger: TransportLogger,
): Promise<PostgresAuthState> {
  const stored = await loadStoredState(pool, botId);
  let keysFlushTimer: ReturnType<typeof setTimeout> | null = null;
  let keysDirty = false;

  const flushKeysNow = async (): Promise<void> => {
    if (keysFlushTimer) {
      clearTimeout(keysFlushTimer);
      keysFlushTimer = null;
    }
    if (!keysDirty) return;
    keysDirty = false;
    try {
      await persist(pool, botId, stored);
    } catch (err) {
      // Флаш вызывается из setTimeout, вне какой-либо цепочки await у
      // вызывающего кода — необработанное исключение здесь становится
      // unhandledRejection и роняет ВЕСЬ процесс gateway, обрывая сессии
      // ВСЕХ ботов на узле, а не только этого (найдено живой ревизией
      // 8.4, 2026-09-21). keysDirty возвращаем в true — несохранённые
      // ключи не теряются молча, следующий set() перепланирует flush.
      keysDirty = true;
      logger.error({ err, botId }, "auth-state keys flush failed, will retry on next update");
    }
  };

  const scheduleKeysFlush = (): void => {
    keysDirty = true;
    if (keysFlushTimer) return;
    keysFlushTimer = setTimeout(() => {
      keysFlushTimer = null;
      void flushKeysNow();
    }, KEYS_FLUSH_DEBOUNCE_MS);
  };

  const saveCreds = async (): Promise<void> => {
    // Немедленно, без debounce: обновление creds никогда не должно теряться.
    // Baileys вызывает это как слушатель "creds.update" и не await'ит/не
    // ловит результат — необработанное исключение здесь тоже уронит весь
    // процесс (тот же класс бага, что и flushKeysNow выше).
    try {
      await persist(pool, botId, stored);
    } catch (err) {
      logger.error({ err, botId }, "auth-state creds persist failed");
    }
  };

  const state: AuthenticationState = {
    creds: stored.creds,
    keys: {
      get: (type, ids) => {
        const bucket = (stored.keys[type] ?? {}) as Record<string, SignalDataTypeMap[typeof type]>;
        const result: { [id: string]: SignalDataTypeMap[typeof type] } = {};
        for (const id of ids) {
          const value = bucket[id];
          if (value !== undefined) {
            result[id] = value;
          }
        }
        return result;
      },
      set: (data: SignalDataSet) => {
        for (const type of Object.keys(data) as (keyof SignalDataTypeMap)[]) {
          const bucket = (stored.keys[type] ??= {});
          const entries = data[type];
          if (!entries) continue;
          for (const [id, value] of Object.entries(entries)) {
            if (value === null || value === undefined) {
              delete bucket[id];
            } else {
              bucket[id] = value;
            }
          }
        }
        scheduleKeysFlush();
      },
    },
  };

  return {
    state,
    saveCreds,
    dispose: flushKeysNow,
  };
}
