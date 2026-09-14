import { QrPanel } from "@/components/QrPanel";
import { fetchBot } from "@/lib/api";
import { API_INTERNAL_URL, API_PROXY_PATH } from "@/lib/env";

export default async function BotOverviewPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const bot = await fetchBot(API_INTERNAL_URL, id);
  if (!bot) {
    // Уже прошли notFound() в layout.tsx (тот же id) — эта ветка практически
    // недостижима, но остаётся на случай гонки между двумя независимыми
    // запросами fetchBot (layout и page получают bota отдельно, Next.js их
    // не передаёт друг другу напрямую).
    return null;
  }
  return <QrPanel initialBot={bot} apiBaseUrl={API_PROXY_PATH} />;
}
