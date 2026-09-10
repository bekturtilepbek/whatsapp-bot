import Link from "next/link";
import { notFound } from "next/navigation";
import { BlockedNumbersTable } from "@/components/BlockedNumbersTable";
import { fetchBlockedNumbers, fetchBot } from "@/lib/api";
import { API_INTERNAL_URL, API_PROXY_PATH } from "@/lib/env";

// Совпадает с BLOCKED_LIST_DEFAULT_LIMIT в services/api/src/api/routers/
// bots.py — BlockedNumbersTable сравнивает длину полученной страницы с этим
// числом, чтобы понять, есть ли ещё номера ("Показать ещё").
const BLOCKED_PAGE_SIZE = 20;

export default async function BotBlockedNumbersPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const bot = await fetchBot(API_INTERNAL_URL, id);
  if (!bot) {
    notFound();
  }
  const numbers = await fetchBlockedNumbers(API_INTERNAL_URL, id, { limit: BLOCKED_PAGE_SIZE });

  return (
    <main>
      <p>
        <Link href={`/bots/${id}`}>← Назад к боту</Link>
      </p>
      <h1>{bot.name} — чёрный список</h1>
      <BlockedNumbersTable
        botId={id}
        apiBaseUrl={API_PROXY_PATH}
        numbers={numbers}
        pageSize={BLOCKED_PAGE_SIZE}
      />
    </main>
  );
}
