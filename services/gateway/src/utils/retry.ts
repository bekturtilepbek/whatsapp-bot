// Ретраи на исходящую отправку (FEATURES.md 4.3, технический долг —
// "Ошибка отправки — лог + ACK, без ретраев" был осознанным упрощением
// Блока 1). Числа зеркалят уже принятый в проекте прецедент LLM-ретраев
// (libs/llm/src/llm/client.py::_call_and_extract): 3 попытки, экспоненциальный
// backoff 1с/2с между ними.
//
// Baileys/WhatsApp не дают чёткой таксономии временных/постоянных ошибок
// (в отличие от OpenAI SDK, где _RETRYABLE_EXCEPTIONS — конкретный список) —
// ретраим ЛЮБУЮ ошибку без попытки классификации (подтверждено пользователем).
// Цена этого упрощения на реально невосстановимом сбое (например logged_out) —
// лишние ~3с backoff перед тем, как сдаться, того же порядка, что и
// существующий SEND_TIMEOUT_MS на одну попытку.
import type { TransportLogger } from "../logger.js";

export const RETRY_MAX_ATTEMPTS = 3;
export const RETRY_BASE_DELAY_MS = 1000;

export async function withRetry<T>(
  fn: () => Promise<T>,
  label: string,
  logger: TransportLogger,
): Promise<T> {
  let lastErr: unknown;
  for (let attempt = 1; attempt <= RETRY_MAX_ATTEMPTS; attempt++) {
    try {
      return await fn();
    } catch (err) {
      lastErr = err;
      if (attempt === RETRY_MAX_ATTEMPTS) break;
      const delay = RETRY_BASE_DELAY_MS * 2 ** (attempt - 1);
      logger.warn({ err, label, attempt, delay }, "outbound send failed, retrying");
      await new Promise((resolve) => setTimeout(resolve, delay));
    }
  }
  throw lastErr;
}
