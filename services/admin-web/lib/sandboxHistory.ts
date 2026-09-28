import type { SandboxHistoryItem } from "@/lib/api";

/** Реальный бот видит последние 50 сообщений (db.messages.fetch_recent_history,
 * limit=50) ВКЛЮЧАЯ текущее; API песочницы принимает history до 50
 * (schemas/sandbox.py) и добавляет новое сообщение сам — шлём 49, чтобы
 * контекст модели совпадал с реальным. Раньше слалась вся история, и после
 * ~25 обменов песочница падала с 422 (2026-09-28). */
export const SANDBOX_HISTORY_LIMIT = 49;

export function toSandboxHistory(
  messages: ReadonlyArray<SandboxHistoryItem>,
): SandboxHistoryItem[] {
  return messages.slice(-SANDBOX_HISTORY_LIMIT).map(({ role, content }) => ({ role, content }));
}
