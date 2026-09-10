// Адреса api — общие для всех Server Component-страниц кабинета.

/** Внутренний адрес api в docker-сети — для SSR-фетчей на сервере и для
 * BFF-прокси (app/api-proxy). */
export const API_INTERNAL_URL = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

/** Путь BFF-прокси на самом admin-web — им пользуются клиентские
 * компоненты вместо прямого адреса api (FEATURES.md 6.18: браузер больше
 * не стучится в api напрямую, только в свой origin). */
export const API_PROXY_PATH = "/api-proxy";
