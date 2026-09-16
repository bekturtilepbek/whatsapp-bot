// Тонкий фетч-слой admin-web поверх api. Используется и на сервере (SSR
// первого рендера, baseUrl = API_INTERNAL_URL) и в браузере (поллинг в
// QrPanel, baseUrl = API_PROXY_PATH — см. app/api-proxy, FEATURES.md 6.18) —
// см. docs/superpowers/specs/2026-09-09-qr-screen-design.md, подход A.

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
  // Живой статус сессии (FEATURES.md 6.17) — connecting/qr/open/reconnecting/
  // logged_out/null. Опционально по той же причине, что settings выше: бэкенд
  // всегда отдаёт оба поля, но старые фикстуры в тестах их не заполняют.
  status?: string | null;
  last_seen?: string | null;
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
  // FEATURES.md 9.10 — авто-реакция на входящее медиа (быстрый фидбек до
  // полноценного ответа), без LLM/тулз.
  media_reaction_enabled?: boolean;
  media_reaction_emoji?: string;
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
  media_reaction_enabled: true,
  media_reaction_emoji: "👍",
};

/** Срезает завершающие "/" — оператор мог вписать NEXT_PUBLIC_API_URL/
 * API_INTERNAL_URL в прод .env с хвостовым слэшем, иначе получаем двойной
 * слэш в пути (`http://host:8000//bots`). Не экспортируется — деталь модуля. */
function normalizeBaseUrl(baseUrl: string): string {
  return baseUrl.replace(/\/+$/, "");
}

/** Общая обёртка вокруг fetch — на сервере (Server Component / Route
 * Handler, typeof window === "undefined") сама подмешивает `Authorization`
 * из cookie сессии admin-web (FEATURES.md 6.18); в браузере просто зовёт
 * fetch как есть — cookie для "/api-proxy" (свой origin) браузер приложит
 * сам. Динамический импорт next/headers — этот модуль не должен тянуться
 * в клиентский бандл (next/headers ломает сборку клиентских компонентов). */
async function apiFetch(url: string, init?: RequestInit): Promise<Response> {
  if (typeof window === "undefined") {
    const { cookies } = await import("next/headers");
    const token = (await cookies()).get("session")?.value;
    if (token) {
      const headers = new Headers(init?.headers);
      headers.set("Authorization", `Bearer ${token}`);
      return fetch(url, { ...init, headers });
    }
  }
  return fetch(url, init);
}

export async function fetchBots(baseUrl: string): Promise<Bot[]> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await apiFetch(`${base}/bots`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`GET /bots failed: ${res.status}`);
  }
  return (await res.json()) as Bot[];
}

export async function fetchBot(baseUrl: string, id: string): Promise<Bot | null> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await apiFetch(`${base}/bots/${id}`, { cache: "no-store" });
  if (res.status === 404) {
    return null;
  }
  if (!res.ok) {
    throw new Error(`GET /bots/${id} failed: ${res.status}`);
  }
  return (await res.json()) as Bot;
}

export async function createBot(baseUrl: string, name: string): Promise<Bot> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await apiFetch(`${base}/bots`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!res.ok) {
    throw new Error(`POST /bots failed: ${res.status}`);
  }
  return (await res.json()) as Bot;
}

export async function logoutBot(baseUrl: string, id: string): Promise<void> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await apiFetch(`${base}/bots/${id}/logout`, { method: "POST" });
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
  const res = await apiFetch(`${base}/bots/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ [field]: body }),
  });
  if (!res.ok) {
    throw new Error(`PATCH /bots/${id} failed: ${res.status}`);
  }
  return (await res.json()) as Bot;
}

/** FEATURES.md 6.3 — переименование бота после создания (BotAccessUser,
 * не только владелец платформы — это витринная строка, не секьюрити). */
export async function patchBotName(baseUrl: string, id: string, name: string): Promise<Bot> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await apiFetch(`${base}/bots/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
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
  const res = await apiFetch(`${base}/bots/${id}/prompts/${kind}/versions`, { cache: "no-store" });
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
  const res = await apiFetch(`${base}/bots/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ settings }),
  });
  if (!res.ok) {
    throw new Error(`PATCH /bots/${id} failed: ${res.status}`);
  }
  return (await res.json()) as Bot;
}

// Decimal (Pydantic v2) сериализуется бэкендом как JSON-строка ("5000.00"),
// не число — см. services/api/src/api/schemas/products.py.
export interface ProductPhoto {
  id: string;
  position: number;
}

export interface Product {
  id: string;
  name: string;
  price: string | null;
  sku: string | null;
  description: string | null;
  display_custom: Record<string, boolean>;
  photos: ProductPhoto[];
  created_at: string;
}

export interface ProductInput {
  name: string;
  price?: number | null;
  sku?: string | null;
  description?: string | null;
  display_custom?: Record<string, boolean>;
}

export interface FetchProductsOptions {
  limit?: number;
  offset?: number;
}

export async function fetchProducts(
  baseUrl: string,
  botId: string,
  options?: FetchProductsOptions,
): Promise<Product[]> {
  const base = normalizeBaseUrl(baseUrl);
  const query = new URLSearchParams();
  if (options?.limit !== undefined) {
    query.set("limit", String(options.limit));
  }
  if (options?.offset !== undefined) {
    query.set("offset", String(options.offset));
  }
  const qs = query.toString();
  const res = await apiFetch(`${base}/bots/${botId}/products${qs ? `?${qs}` : ""}`, {
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`GET /bots/${botId}/products failed: ${res.status}`);
  }
  return (await res.json()) as Product[];
}

export async function fetchProduct(
  baseUrl: string,
  botId: string,
  productId: string,
): Promise<Product | null> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await apiFetch(`${base}/bots/${botId}/products/${productId}`, { cache: "no-store" });
  if (res.status === 404) {
    return null;
  }
  if (!res.ok) {
    throw new Error(`GET /bots/${botId}/products/${productId} failed: ${res.status}`);
  }
  return (await res.json()) as Product;
}

/** Собирает multipart/form-data — поле опускается целиком, если его
 * значение null/undefined/пусто (не отправляем пустую строку вместо
 * отсутствующего поля: на бэкенде Form(None)-параметр для Decimal не
 * умеет коэрсить "" в None, только реальное отсутствие ключа). */
function buildProductFormData(input: ProductInput, photos: File[]): FormData {
  const form = new FormData();
  form.set("name", input.name);
  if (input.price !== null && input.price !== undefined) {
    form.set("price", String(input.price));
  }
  if (input.sku !== null && input.sku !== undefined) {
    form.set("sku", input.sku);
  }
  if (input.description !== null && input.description !== undefined) {
    form.set("description", input.description);
  }
  if (input.display_custom !== undefined) {
    form.set("display_custom", JSON.stringify(input.display_custom));
  }
  for (const photo of photos) {
    form.append("photos", photo);
  }
  return form;
}

export async function createProduct(
  baseUrl: string,
  botId: string,
  input: ProductInput,
  photos: File[],
): Promise<Product> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await apiFetch(`${base}/bots/${botId}/products`, {
    method: "POST",
    body: buildProductFormData(input, photos),
  });
  if (!res.ok) {
    throw new Error(`POST /bots/${botId}/products failed: ${res.status}`);
  }
  return (await res.json()) as Product;
}

export async function updateProduct(
  baseUrl: string,
  botId: string,
  productId: string,
  input: ProductInput,
): Promise<Product> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await apiFetch(`${base}/bots/${botId}/products/${productId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    throw new Error(`PATCH /bots/${botId}/products/${productId} failed: ${res.status}`);
  }
  return (await res.json()) as Product;
}

export async function deleteProduct(
  baseUrl: string,
  botId: string,
  productId: string,
): Promise<void> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await apiFetch(`${base}/bots/${botId}/products/${productId}`, { method: "DELETE" });
  if (!res.ok) {
    throw new Error(`DELETE /bots/${botId}/products/${productId} failed: ${res.status}`);
  }
}

export async function addProductPhotos(
  baseUrl: string,
  botId: string,
  productId: string,
  photos: File[],
): Promise<ProductPhoto[]> {
  const base = normalizeBaseUrl(baseUrl);
  const form = new FormData();
  for (const photo of photos) {
    form.append("photos", photo);
  }
  const res = await apiFetch(`${base}/bots/${botId}/products/${productId}/photos`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    throw new Error(`POST /bots/${botId}/products/${productId}/photos failed: ${res.status}`);
  }
  return (await res.json()) as ProductPhoto[];
}

export async function deleteProductPhoto(
  baseUrl: string,
  botId: string,
  productId: string,
  photoId: string,
): Promise<void> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await apiFetch(`${base}/bots/${botId}/products/${productId}/photos/${photoId}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    throw new Error(
      `DELETE /bots/${botId}/products/${productId}/photos/${photoId} failed: ${res.status}`,
    );
  }
}

export function productPhotoUrl(
  baseUrl: string,
  botId: string,
  productId: string,
  photoId: string,
): string {
  const base = normalizeBaseUrl(baseUrl);
  return `${base}/bots/${botId}/products/${productId}/photos/${photoId}`;
}

// Чёрный список номеров (FEATURES.md 1.5/6.9).

export interface BlockedNumber {
  phone: string;
}

export interface FetchBlockedNumbersOptions {
  limit?: number;
  offset?: number;
}

export async function fetchBlockedNumbers(
  baseUrl: string,
  botId: string,
  options?: FetchBlockedNumbersOptions,
): Promise<BlockedNumber[]> {
  const base = normalizeBaseUrl(baseUrl);
  const query = new URLSearchParams();
  if (options?.limit !== undefined) {
    query.set("limit", String(options.limit));
  }
  if (options?.offset !== undefined) {
    query.set("offset", String(options.offset));
  }
  const qs = query.toString();
  const res = await apiFetch(`${base}/bots/${botId}/blocked-numbers${qs ? `?${qs}` : ""}`, {
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`GET /bots/${botId}/blocked-numbers failed: ${res.status}`);
  }
  return (await res.json()) as BlockedNumber[];
}

export async function addBlockedNumber(
  baseUrl: string,
  botId: string,
  phone: string,
): Promise<BlockedNumber> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await apiFetch(`${base}/bots/${botId}/blocked-numbers`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ phone }),
  });
  if (!res.ok) {
    throw new Error(`POST /bots/${botId}/blocked-numbers failed: ${res.status}`);
  }
  return (await res.json()) as BlockedNumber;
}

export async function deleteBlockedNumber(
  baseUrl: string,
  botId: string,
  phone: string,
): Promise<void> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await apiFetch(`${base}/bots/${botId}/blocked-numbers/${phone}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    throw new Error(`DELETE /bots/${botId}/blocked-numbers/${phone} failed: ${res.status}`);
  }
}

// Пользователи кабинета (FEATURES.md 6.18, только для владельца платформы).

export interface CabinetUser {
  id: string;
  email: string;
  is_platform_owner: boolean;
  is_active: boolean;
  bot_ids: string[];
}

export async function fetchUsers(baseUrl: string): Promise<CabinetUser[]> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await apiFetch(`${base}/users`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`GET /users failed: ${res.status}`);
  }
  return (await res.json()) as CabinetUser[];
}

export async function createUser(
  baseUrl: string,
  input: { email: string; password: string; bot_ids: string[] },
): Promise<CabinetUser> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await apiFetch(`${base}/users`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    throw new Error(`POST /users failed: ${res.status}`);
  }
  return (await res.json()) as CabinetUser;
}

export async function grantBotAccess(baseUrl: string, userId: string, botId: string): Promise<void> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await apiFetch(`${base}/users/${userId}/bot-access`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ bot_id: botId }),
  });
  if (!res.ok) {
    throw new Error(`POST /users/${userId}/bot-access failed: ${res.status}`);
  }
}

export async function revokeBotAccess(baseUrl: string, userId: string, botId: string): Promise<void> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await apiFetch(`${base}/users/${userId}/bot-access/${botId}`, { method: "DELETE" });
  if (!res.ok) {
    throw new Error(`DELETE /users/${userId}/bot-access/${botId} failed: ${res.status}`);
  }
}

export async function patchUser(
  baseUrl: string,
  userId: string,
  patch: { is_active?: boolean; password?: string },
): Promise<CabinetUser> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await apiFetch(`${base}/users/${userId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) {
    throw new Error(`PATCH /users/${userId} failed: ${res.status}`);
  }
  return (await res.json()) as CabinetUser;
}

// Документы бота (FEATURES.md 6.7).

export interface BotDocument {
  id: string;
  filename: string;
  mime_type: string;
  created_at: string;
}

export async function fetchDocuments(baseUrl: string, botId: string): Promise<BotDocument[]> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await apiFetch(`${base}/bots/${botId}/documents`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`GET /bots/${botId}/documents failed: ${res.status}`);
  }
  return (await res.json()) as BotDocument[];
}

export async function uploadDocument(
  baseUrl: string,
  botId: string,
  file: File,
): Promise<BotDocument> {
  const base = normalizeBaseUrl(baseUrl);
  const form = new FormData();
  form.set("file", file);
  const res = await apiFetch(`${base}/bots/${botId}/documents`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    throw new Error(`POST /bots/${botId}/documents failed: ${res.status}`);
  }
  return (await res.json()) as BotDocument;
}

export async function deleteDocument(
  baseUrl: string,
  botId: string,
  documentId: string,
): Promise<void> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await apiFetch(`${base}/bots/${botId}/documents/${documentId}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    throw new Error(`DELETE /bots/${botId}/documents/${documentId} failed: ${res.status}`);
  }
}

// Аудит-лог (FEATURES.md 6.19, только для владельца платформы).

export interface AuditLogEntry {
  id: string;
  actor_user_id: string;
  actor_email: string;
  bot_id: string | null;
  bot_name: string | null;
  action: string;
  payload: Record<string, unknown> | null;
  created_at: string;
}

export interface FetchAuditLogOptions {
  botId?: string;
  limit?: number;
  offset?: number;
}

export async function fetchAuditLog(
  baseUrl: string,
  options?: FetchAuditLogOptions,
): Promise<AuditLogEntry[]> {
  const base = normalizeBaseUrl(baseUrl);
  const query = new URLSearchParams();
  if (options?.botId) {
    query.set("bot_id", options.botId);
  }
  if (options?.limit !== undefined) {
    query.set("limit", String(options.limit));
  }
  if (options?.offset !== undefined) {
    query.set("offset", String(options.offset));
  }
  const qs = query.toString();
  const res = await apiFetch(`${base}/audit-log${qs ? `?${qs}` : ""}`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`GET /audit-log failed: ${res.status}`);
  }
  return (await res.json()) as AuditLogEntry[];
}

// Расходы OpenAI (FEATURES.md 6.15, только для владельца платформы).
// cost — Decimal на бэкенде, сериализуется как JSON-строка (не число), см.
// комментарий у Product.price в этом же файле — тот же приём Pydantic v2.

export type UsagePeriod = "7d" | "30d" | "90d" | "all";

export interface UsageSummary {
  bot_id: string;
  bot_name: string;
  tokens_in: number;
  tokens_out: number;
  cost: string;
}

export async function fetchUsage(
  baseUrl: string,
  period: UsagePeriod = "30d",
): Promise<UsageSummary[]> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await apiFetch(`${base}/usage?period=${period}`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`GET /usage failed: ${res.status}`);
  }
  return (await res.json()) as UsageSummary[];
}

// Песочница (FEATURES.md 9.6, только для владельца платформы) — без тулз,
// история хранится целиком в браузере (ничего не пишется в contacts/messages
// на бэкенде, см. services/api/src/api/routers/sandbox.py).

export interface SandboxHistoryItem {
  role: "user" | "assistant";
  content: string;
}

export interface SandboxMediaItem {
  storage_key: string;
  mime_type: string;
  filename: string | null;
}

export interface SandboxMessageResult {
  reply: string;
  tokens_in: number;
  tokens_out: number;
  model: string;
  media: SandboxMediaItem[];
}

export async function sendSandboxMessage(
  baseUrl: string,
  botId: string,
  history: SandboxHistoryItem[],
  message: string,
): Promise<SandboxMessageResult> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await apiFetch(`${base}/bots/${botId}/sandbox/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ history, message }),
  });
  if (!res.ok) {
    throw new Error(`POST /bots/${botId}/sandbox/messages failed: ${res.status}`);
  }
  return (await res.json()) as SandboxMessageResult;
}

// Медиа из тулзы (карточка товара, файл) — эфемерное, не хранится нигде для
// песочницы отдельно, поэтому mime_type передаётся в самом URL (см.
// services/api/src/api/routers/sandbox.py::get_sandbox_media).
export function sandboxMediaUrl(
  baseUrl: string,
  botId: string,
  storageKey: string,
  mimeType: string,
): string {
  const base = normalizeBaseUrl(baseUrl);
  const key = encodeURIComponent(storageKey);
  const mime = encodeURIComponent(mimeType);
  return `${base}/bots/${botId}/sandbox/media?key=${key}&mime_type=${mime}`;
}
