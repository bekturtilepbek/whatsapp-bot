import { QrPanel } from "@/components/QrPanel";
import { StatTile } from "@/components/ui/StatTile";
import { fetchBot, fetchBotStats } from "@/lib/api";
import { API_INTERNAL_URL, API_PROXY_PATH } from "@/lib/env";

export default async function BotOverviewPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const [bot, stats] = await Promise.all([
    fetchBot(API_INTERNAL_URL, id),
    fetchBotStats(API_INTERNAL_URL, id),
  ]);
  if (!bot) {
    // Уже прошли notFound() в layout.tsx (тот же id) — Next.js дедуплицирует
    // одинаковые fetch() в рамках одного рендер-прохода (React.cache), так
    // что оба вызова fetchBot схлопываются в один HTTP-запрос и один и тот
    // же снэпшот — гонки здесь нет. Ветка остаётся на случай, если notFound()
    // в layout почему-то не сработал.
    return null;
  }
  return (
    <main className="space-y-5">
      <div className="grid grid-cols-2 gap-5 sm:max-w-md">
        <StatTile label="Сообщений всего" value={stats.messages_count} />
        <StatTile label="Контактов" value={stats.contacts_count} />
      </div>
      <QrPanel initialBot={bot} apiBaseUrl={API_PROXY_PATH} />
    </main>
  );
}
