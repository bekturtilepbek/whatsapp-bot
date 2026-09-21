// Кабинет обслуживает бота в Бишкеке — всё время в интерфейсе показываем в
// Asia/Bishkek (UTC+6), а не в браузерной таймзоне зрителя. Явные locale
// ("ru-RU") и timeZone делают форматирование детерминированным: одна и та же
// ISO-строка всегда даёт одну и ту же строку и на сервере, и на клиенте,
// независимо от TZ окружения — безопасно при SSR (в отличие от прежнего
// приёма "iso.slice(0, 16)", который просто показывал сырой UTC).
const BISHKEK_TIME_ZONE = "Asia/Bishkek";

const dateTimeFormatter = new Intl.DateTimeFormat("ru-RU", {
  timeZone: BISHKEK_TIME_ZONE,
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

const timeFormatter = new Intl.DateTimeFormat("ru-RU", {
  timeZone: BISHKEK_TIME_ZONE,
  hour: "2-digit",
  minute: "2-digit",
});

/** Дата и время по Бишкеку, напр. "22.09.2026, 14:05". */
export function formatBishkekDateTime(iso: string): string {
  return dateTimeFormatter.format(new Date(iso));
}

/** Только время по Бишкеку, напр. "14:05" — для контекстов вроде чата. */
export function formatBishkekTime(iso: string): string {
  return timeFormatter.format(new Date(iso));
}
