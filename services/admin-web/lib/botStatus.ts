// Единая логика статуса подключения бота (FEATURES.md 6.17) —
// переиспользуется везде, где показывается StatusPulse: карточка бота
// (app/bots/[id]/layout.tsx) и список ботов (components/BotsTable.tsx).
// Раньше жила только в layout.tsx — вынесена сюда, чтобы список ботов не
// завёл свою версию с тем же багом, что уже был найден и исправлен на
// карточке бота (финальное ревью cabinet-redesign-foundation, 2026-09-15):
// bot.status — источник истины, linked_at — только фолбэк для старых
// фикстур без этого поля. Только 2 UI-статуса (не 5 сырых) — "подключается"
// сознательно схлопнут в "не подключён" по прямому запросу пользователя.
import type { Bot } from "@/lib/api";
import type { BotConnectionStatus } from "@/components/ui/StatusPulse";

export function toConnectionStatus(bot: Bot): BotConnectionStatus {
  switch (bot.status) {
    case "open":
      return "connected";
    case "connecting":
    case "qr":
    case "reconnecting":
    case "logged_out":
      return "disconnected";
    default:
      return bot.linked_at ? "connected" : "disconnected";
  }
}
