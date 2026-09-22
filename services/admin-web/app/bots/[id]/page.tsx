import { QrPanel } from "@/components/QrPanel";
import { fetchBot, fetchBotStats } from "@/lib/api";
import { fetchCurrentUser } from "@/lib/currentUser";
import { API_INTERNAL_URL, API_PROXY_PATH } from "@/lib/env";

export default async function BotOverviewPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const [bot, stats, user] = await Promise.all([
    fetchBot(API_INTERNAL_URL, id),
    fetchBotStats(API_INTERNAL_URL, id),
    fetchCurrentUser(),
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
    <main>
      <QrPanel
        initialBot={bot}
        apiBaseUrl={API_PROXY_PATH}
        stats={stats}
        canManageConnection={user?.role !== "client"}
      />
    </main>
  );
}
