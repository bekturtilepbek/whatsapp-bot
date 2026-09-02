// Запросы к bots/bot_sessions для управления сессиями (шаг 4a STAGE1_CORE).
import type { Pool } from "pg";

/**
 * Боты, у которых уже есть сохранённые creds (были привязаны раньше).
 * Сессии для них поднимаются при старте gateway независимо от bots.enabled —
 * флаг проверяет worker в пайплайне, транспорт не молчит сам по себе.
 * Разрыв сессии — только явный logout.
 */
export async function listLinkedBotIds(pool: Pool): Promise<string[]> {
  const { rows } = await pool.query<{ bot_id: string }>(
    `SELECT bot_id
       FROM bot_sessions
      WHERE auth_state -> 'creds' ->> 'registered' = 'true'`,
  );
  return rows.map((r) => r.bot_id);
}

export async function botExists(pool: Pool, botId: string): Promise<boolean> {
  const { rows } = await pool.query<{ exists: boolean }>(
    "SELECT EXISTS(SELECT 1 FROM bots WHERE id = $1) AS exists",
    [botId],
  );
  return rows[0]?.exists ?? false;
}

export async function markLinked(pool: Pool, botId: string, phone: string | undefined): Promise<void> {
  await pool.query(
    `INSERT INTO bot_sessions (bot_id, phone, linked_at, last_seen)
     VALUES ($1, $2, now(), now())
     ON CONFLICT (bot_id) DO UPDATE
        SET phone = EXCLUDED.phone,
            linked_at = COALESCE(bot_sessions.linked_at, EXCLUDED.linked_at),
            last_seen = now()`,
    [botId, phone ?? null],
  );
}

export async function touchLastSeen(pool: Pool, botId: string): Promise<void> {
  await pool.query("UPDATE bot_sessions SET last_seen = now() WHERE bot_id = $1", [botId]);
}

export async function clearSession(pool: Pool, botId: string): Promise<void> {
  await pool.query(
    `UPDATE bot_sessions
        SET auth_state = '{}'::jsonb, phone = NULL, linked_at = NULL
      WHERE bot_id = $1`,
    [botId],
  );
}
