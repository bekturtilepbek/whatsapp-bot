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
  // Сотрудник (роль prompter), ведущий бота (FEATURES.md 6.18) — опционально
  // по той же причине, что остальные поля выше. email — витринное поле,
  // сырой id нигде в UI не показываем.
  responsible_user_id?: string | null;
  responsible_user_email?: string | null;
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
  // Волна 4 — модель LLM per bot. Захардкоженный список на фронте
  // (подтверждено пользователем) — свободный текст рискует тихо сломать
  // бота опечаткой/несуществующей моделью. Отсутствует у ботов, заведённых
  // до этой настройки — падает в платформенный OPENAI_MODEL (см.
  // libs/llm/src/llm/client.py::current_model).
  model?: string;
  // FEATURES.md 4.5 — глобальный вывод карточки товара. Тот же трёхключевой
  // формат, что и Product.display_custom (ProductForm.tsx) — бэкенд
  // (product_search.py::_resolve_display_config) читает его как fallback,
  // когда на конкретном товаре нет своего display_custom («всё или
  // ничего»). Раньше в кабинете не было формы для этого поля вообще —
  // только per-товар переопределение.
  product_display?: ProductDisplay;
}

export interface ProductDisplay {
  show_name?: boolean;
  show_description?: boolean;
  show_price?: boolean;
}

// gpt-6-luna — новая модель OpenAI (релиз 2026-09-22), дефолт с 2026-09-28
// по запросу пользователя; gpt-4o-mini/gpt-4o оставлены в списке — у части
// ботов они уже выбраны явно в settings.model, список не должен осиротить
// их выбор из выпадающего меню.
export const AVAILABLE_MODELS = ["gpt-6-luna", "gpt-4o-mini", "gpt-4o"] as const;

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
  model: AVAILABLE_MODELS[0],
  product_display: { show_name: true, show_description: true, show_price: true },
};

/** Срезает завершающие "/" — оператор мог вписать API_INTERNAL_URL в прод
 * .env с хвостовым слэшем, иначе получаем двойной слэш в пути
 * (`http://host:8000//bots`). Не экспортируется — деталь модуля. */
function normalizeBaseUrl(baseUrl: string): string {
  return baseUrl.replace(/\/+$/, "");
}

/** Общая обёртка вокруг fetch — на сервере (Server Component / Route
 * Handler, typeof window === "undefined") сама подмешивает `Authorization`
 * из cookie сессии admin-web (FEATURES.md 6.18); в браузере просто зовёт
 * fetch как есть — cookie для "/api-proxy" (свой origin) браузер приложит
 * сам. Динамический импорт next/headers — этот модуль не должен тянуться
 * в клиентский бандл (next/headers ломает сборку клиентских компонентов).
 *
 * 401 от api на сервере значит "cookie есть, но api её не принял"
 * (просрочен/невалиден JWT — middleware.ts проверяет только присутствие
 * cookie, не её валидность). Редирект на /login напрямую тут не годится:
 * cookie формально ещё есть, middleware отобьёт /login обратно на /bots
 * (см. middleware.ts, "hasSession && isLoginPage") — бесконечный цикл.
 * Вместо этого — редирект на Route Handler, который умеет стереть cookie
 * (Server Component этого не может при рендере, Next 15). */
async function apiFetch(url: string, init?: RequestInit): Promise<Response> {
  if (typeof window === "undefined") {
    const { cookies } = await import("next/headers");
    const token = (await cookies()).get("session")?.value;
    if (token) {
      const headers = new Headers(init?.headers);
      headers.set("Authorization", `Bearer ${token}`);
      const res = await fetch(url, { ...init, headers });
      if (res.status === 401) {
        const { redirect } = await import("next/navigation");
        redirect("/api/session-expired");
      }
      return res;
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
  // 403 — бот есть, но без гранта у этого пользователя (чужой URL): для
  // кабинета это то же "нет такого бота", иначе layout бота падает в
  // Application error. Заодно не раскрываем, что бот с таким id существует.
  // 422 — id в URL вообще не UUID (битая/вручную набранная ссылка).
  if (res.status === 404 || res.status === 403 || res.status === 422) {
    return null;
  }
  if (!res.ok) {
    throw new Error(`GET /bots/${id} failed: ${res.status}`);
  }
  return (await res.json()) as Bot;
}

export async function createBot(
  baseUrl: string,
  name: string,
  responsibleUserId?: string | null,
): Promise<Bot> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await apiFetch(`${base}/bots`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, responsible_user_id: responsibleUserId ?? null }),
  });
  if (!res.ok) {
    throw new Error(`POST /bots failed: ${res.status}`);
  }
  return (await res.json()) as Bot;
}

// FEATURES.md 6.18 — выбор ответственного (только роль prompter) при
// создании/настройке бота. Узкая схема (id+email only) — доступна и Admin
// (PlatformWide), не только Superadmin, в отличие от fetchUsers/GET /users.
export interface PrompterBrief {
  id: string;
  email: string;
}

export async function fetchPrompters(baseUrl: string): Promise<PrompterBrief[]> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await apiFetch(`${base}/users/prompters`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`GET /users/prompters failed: ${res.status}`);
  }
  return (await res.json()) as PrompterBrief[];
}

/** Смена ответственного на вкладке "Настройки" (тот же роут, что
 * patchBotName/patchBotSettings — все три поля живут в BotPatch,
 * FullBotAccess). null снимает ответственного явно (отличается от "не
 * менять" — бэкенд различает по наличию ключа в теле). */
export async function patchBotResponsibleUser(
  baseUrl: string,
  id: string,
  responsibleUserId: string | null,
): Promise<Bot> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await apiFetch(`${base}/bots/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ responsible_user_id: responsibleUserId }),
  });
  if (!res.ok) {
    throw new Error(`PATCH /bots/${id} failed: ${res.status}`);
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

// Стат-плитки вкладки "Обзор" — отдельная ручка (services/api/src/api/schemas/bots.py::BotStats),
// не поле Bot, см. комментарий там же.
export interface BotStats {
  messages_count: number;
  contacts_count: number;
}

export async function fetchBotStats(baseUrl: string, id: string): Promise<BotStats> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await apiFetch(`${base}/bots/${id}/stats`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`GET /bots/${id}/stats failed: ${res.status}`);
  }
  return (await res.json()) as BotStats;
}

// Вкладка "Активные чаты" (FEATURES.md 5.3) — чаты, которые сейчас ведёт
// человек, не бот. contact_* — best-effort подсказка с бэкенда, может
// отсутствовать (см. services/api/src/api/schemas/bots.py::ActiveChatOut).
export interface ActiveChat {
  chat_id: string;
  contact_name: string | null;
  contact_phone: string | null;
  auto_release_in_seconds: number | null;
}

export async function fetchActiveChats(baseUrl: string, id: string): Promise<ActiveChat[]> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await apiFetch(`${base}/bots/${id}/chats`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`GET /bots/${id}/chats failed: ${res.status}`);
  }
  return (await res.json()) as ActiveChat[];
}

export async function releaseChat(baseUrl: string, id: string, chatId: string): Promise<void> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await apiFetch(`${base}/bots/${id}/chats/${encodeURIComponent(chatId)}/release`, {
    method: "POST",
  });
  if (!res.ok) {
    throw new Error(`POST /bots/${id}/chats/${chatId}/release failed: ${res.status}`);
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
  const res = await apiFetch(`${base}/bots/${id}/prompts`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ [field]: body }),
  });
  if (!res.ok) {
    throw new Error(`PATCH /bots/${id}/prompts failed: ${res.status}`);
  }
  return (await res.json()) as Bot;
}

/** FEATURES.md 6.3 — переименование бота после создания. Живёт на
 * /bots/{id} вместе с settings (FullBotAccess — недоступно роли client,
 * см. lib/currentUser.ts и services/api/src/api/security.py). */
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

/** FEATURES.md 1.7 — пауза бота. Свой роут (не /bots/{id}) — доступен и
 * роли client (тумблер на вкладке "Обзор"), в отличие от имени/настроек. */
export async function patchBotEnabled(baseUrl: string, id: string, enabled: boolean): Promise<Bot> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await apiFetch(`${base}/bots/${id}/enabled`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
  if (!res.ok) {
    throw new Error(`PATCH /bots/${id}/enabled failed: ${res.status}`);
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

// FEATURES.md 4.13/4.7 — реестр тулз бота. Сейчас в кабинете есть UI только
// под send_telegram_lead (components/TelegramLeadToolForm.tsx); список/save/
// delete — общие ручки, подойдут под будущие тулзы без изменений здесь.
export interface ToolBinding {
  tool_name: string;
  config: Record<string, unknown>;
}

export async function fetchBotTools(baseUrl: string, id: string): Promise<ToolBinding[]> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await apiFetch(`${base}/bots/${id}/tools`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`GET /bots/${id}/tools failed: ${res.status}`);
  }
  return (await res.json()) as ToolBinding[];
}

export async function saveBotTool(
  baseUrl: string,
  id: string,
  toolName: string,
  config: Record<string, unknown>,
): Promise<ToolBinding> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await apiFetch(`${base}/bots/${id}/tools`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tool_name: toolName, config }),
  });
  if (!res.ok) {
    throw new Error(`POST /bots/${id}/tools failed: ${res.status}`);
  }
  return (await res.json()) as ToolBinding;
}

export async function deleteBotTool(baseUrl: string, id: string, toolName: string): Promise<void> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await apiFetch(`${base}/bots/${id}/tools/${toolName}`, { method: "DELETE" });
  if (!res.ok) {
    throw new Error(`DELETE /bots/${id}/tools/${toolName} failed: ${res.status}`);
  }
}

// Decimal (Pydantic v2) сериализуется бэкендом как JSON-строка ("5000.00"),
// не число — см. services/api/src/api/schemas/products.py.
export interface ProductMedia {
  id: string;
  position: number;
  // Фото или видео (FEATURES.md 4.4 ревизия) — фронт решает по префиксу,
  // рендерить <img> или <video>.
  mime_type: string;
}

export interface Product {
  id: string;
  name: string;
  price: string | null;
  sku: string | null;
  description: string | null;
  display_custom: Record<string, boolean>;
  media: ProductMedia[];
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
  // 422 — productId в URL не UUID: для страницы это то же "нет такого товара".
  if (res.status === 404 || res.status === 422) {
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
function buildProductFormData(input: ProductInput, media: File[]): FormData {
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
  for (const item of media) {
    form.append("media", item);
  }
  return form;
}

export async function createProduct(
  baseUrl: string,
  botId: string,
  input: ProductInput,
  media: File[],
): Promise<Product> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await apiFetch(`${base}/bots/${botId}/products`, {
    method: "POST",
    body: buildProductFormData(input, media),
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

export async function addProductMedia(
  baseUrl: string,
  botId: string,
  productId: string,
  media: File[],
): Promise<ProductMedia[]> {
  const base = normalizeBaseUrl(baseUrl);
  const form = new FormData();
  for (const item of media) {
    form.append("media", item);
  }
  const res = await apiFetch(`${base}/bots/${botId}/products/${productId}/media`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    throw new Error(`POST /bots/${botId}/products/${productId}/media failed: ${res.status}`);
  }
  return (await res.json()) as ProductMedia[];
}

export async function deleteProductMedia(
  baseUrl: string,
  botId: string,
  productId: string,
  mediaId: string,
): Promise<void> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await apiFetch(`${base}/bots/${botId}/products/${productId}/media/${mediaId}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    throw new Error(
      `DELETE /bots/${botId}/products/${productId}/media/${mediaId} failed: ${res.status}`,
    );
  }
}

export function productMediaUrl(
  baseUrl: string,
  botId: string,
  productId: string,
  mediaId: string,
): string {
  const base = normalizeBaseUrl(baseUrl);
  return `${base}/bots/${botId}/products/${productId}/media/${mediaId}`;
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

// Пользователи кабинета (FEATURES.md 6.18, только для суперадмина).

export type CabinetUserRole = "superadmin" | "admin" | "prompter" | "client";

export interface CabinetUser {
  id: string;
  email: string;
  role: CabinetUserRole;
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
  input: {
    email: string;
    password: string;
    role: Exclude<CabinetUserRole, "superadmin">;
    bot_ids: string[];
  },
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
  patch: {
    is_active?: boolean;
    password?: string;
    role?: Exclude<CabinetUserRole, "superadmin">;
  },
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

// Фото/PDF от "клиента" в песочнице (FEATURES.md 9.6 часть B) — зеркало
// _reply_with_vision/_reply_with_pdf, без записи файла в Storage.
export async function sendSandboxMediaMessage(
  baseUrl: string,
  botId: string,
  history: SandboxHistoryItem[],
  file: File,
  caption?: string,
): Promise<SandboxMessageResult> {
  const base = normalizeBaseUrl(baseUrl);
  const form = new FormData();
  form.append("file", file);
  form.append("history", JSON.stringify(history));
  if (caption) {
    form.append("caption", caption);
  }
  const res = await apiFetch(`${base}/bots/${botId}/sandbox/media-messages`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    throw new Error(`POST /bots/${botId}/sandbox/media-messages failed: ${res.status}`);
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
