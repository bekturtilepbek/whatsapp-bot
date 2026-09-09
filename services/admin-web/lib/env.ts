// Адреса api — общие для всех Server Component-страниц кабинета. Раньше
// каждая страница объявляла эти две константы у себя (4 копии); вынесено
// сюда, чтобы смена дефолтного хоста/порта не пропустила один файл (найдено
// code review настроек бота, 2026-09-09).

/** Внутренний адрес api в docker-сети — для SSR-фетчей на сервере. */
export const API_INTERNAL_URL = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

/** Публичный адрес api, каким его видит браузер — для client-компонентов
 * (поллинг в QrPanel, сохранение в PromptEditor/BotSettingsForm). */
export const API_PUBLIC_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
