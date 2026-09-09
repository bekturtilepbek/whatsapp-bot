// Тонкий фетч-слой admin-web поверх api. Используется и на сервере (SSR
// первого рендера, baseUrl = API_INTERNAL_URL) и в браузере (поллинг в
// QrPanel, baseUrl = NEXT_PUBLIC_API_URL) — см. docs/superpowers/specs/
// 2026-09-09-qr-screen-design.md, подход A.

export interface Bot {
  id: string;
  name: string;
  enabled: boolean;
  phone: string | null;
  linked_at: string | null;
  system_prompt: string;
  image_prompt: string | null;
  pdf_prompt: string | null;
  // Опционально (не как остальные поля выше) — bots.settings свободный dict
  // на бэкенде, старые фикстуры в тестах его не заполняют и не обязаны.
  settings?: BotSettings;
}

// FEATURES.md 6.11 — настройки бота. Все поля опциональны: bots.settings —
// свободный JSONB-dict, отсутствующий ключ читается downstream-кодом с его
// собственным дефолтом (см. DEFAULT_BOT_SETTINGS — та же логика, продублирована
// здесь для формы настроек, значения см. в services/worker/src/worker/pipeline/
// consumer.py, services/celery/src/tasks/followup.py, services/gateway/src/db/bots.ts).
export interface BotSettings {
  batch_timeout_seconds?: number;
  auto_release_minutes?: number;
  reminder_enabled?: boolean;
  reminder_delay_minutes?: number;
  reminder_message?: string;
  media_fallback_text?: string;
  media_max_size_bytes?: number;
}

export const DEFAULT_BOT_SETTINGS: Required<BotSettings> = {
  batch_timeout_seconds: 1,
  auto_release_minutes: 12,
  reminder_enabled: false,
  reminder_delay_minutes: 60,
  reminder_message:
    "Здравствуйте! Подскажите, удалось ли ознакомиться с информацией? Если есть вопросы — я на связи!",
  media_fallback_text: "Пока я умею отвечать только на текстовые сообщения",
  media_max_size_bytes: 16 * 1024 * 1024,
};

/** Срезает завершающие "/" — оператор мог вписать NEXT_PUBLIC_API_URL/
 * API_INTERNAL_URL в прод .env с хвостовым слэшем, иначе получаем двойной
 * слэш в пути (`http://host:8000//bots`). Не экспортируется — деталь модуля. */
function normalizeBaseUrl(baseUrl: string): string {
  return baseUrl.replace(/\/+$/, "");
}

export async function fetchBots(baseUrl: string): Promise<Bot[]> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await fetch(`${base}/bots`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`GET /bots failed: ${res.status}`);
  }
  return (await res.json()) as Bot[];
}

export async function fetchBot(baseUrl: string, id: string): Promise<Bot | null> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await fetch(`${base}/bots/${id}`, { cache: "no-store" });
  if (res.status === 404) {
    return null;
  }
  if (!res.ok) {
    throw new Error(`GET /bots/${id} failed: ${res.status}`);
  }
  return (await res.json()) as Bot;
}

export async function logoutBot(baseUrl: string, id: string): Promise<void> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await fetch(`${base}/bots/${id}/logout`, { method: "POST" });
  if (!res.ok) {
    throw new Error(`POST /bots/${id}/logout failed: ${res.status}`);
  }
}

/** Query-параметр — cache-busting: без него браузер закэширует PNG по URL и
 * не подхватит смену QR при ротации WhatsApp (~раз в 20с). */
export function qrImageUrl(baseUrl: string, id: string): string {
  const base = normalizeBaseUrl(baseUrl);
  return `${base}/bots/${id}/qr?t=${Date.now()}`;
}

export type PromptKind = "main" | "image" | "pdf";

export interface PromptVersion {
  id: string;
  body: string | null;
  author: string;
  created_at: string;
}

const PROMPT_FIELD_BY_KIND: Record<PromptKind, "system_prompt" | "image_prompt" | "pdf_prompt"> = {
  main: "system_prompt",
  image: "image_prompt",
  pdf: "pdf_prompt",
};

export async function patchBotPrompt(
  baseUrl: string,
  id: string,
  kind: PromptKind,
  body: string,
): Promise<Bot> {
  const base = normalizeBaseUrl(baseUrl);
  const field = PROMPT_FIELD_BY_KIND[kind];
  const res = await fetch(`${base}/bots/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ [field]: body }),
  });
  if (!res.ok) {
    throw new Error(`PATCH /bots/${id} failed: ${res.status}`);
  }
  return (await res.json()) as Bot;
}

export async function fetchPromptVersions(
  baseUrl: string,
  id: string,
  kind: PromptKind,
): Promise<PromptVersion[]> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await fetch(`${base}/bots/${id}/prompts/${kind}/versions`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`GET /bots/${id}/prompts/${kind}/versions failed: ${res.status}`);
  }
  return (await res.json()) as PromptVersion[];
}

/** Шаллоу JSONB-merge на бэкенде (update_bot) — можно передавать только
 * изменившиеся ключи, но форма настроек всегда шлёт весь объект целиком
 * (см. components/BotSettingsForm.tsx). */
export async function patchBotSettings(
  baseUrl: string,
  id: string,
  settings: BotSettings,
): Promise<Bot> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await fetch(`${base}/bots/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ settings }),
  });
  if (!res.ok) {
    throw new Error(`PATCH /bots/${id} failed: ${res.status}`);
  }
  return (await res.json()) as Bot;
}
