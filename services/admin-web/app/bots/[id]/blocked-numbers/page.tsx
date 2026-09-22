import { notFound, redirect } from "next/navigation";
import { BlockedNumbersTable } from "@/components/BlockedNumbersTable";
import { fetchBlockedNumbers, fetchBot } from "@/lib/api";
import { fetchCurrentUser } from "@/lib/currentUser";
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
  // client урезан (FullBotAccess) — GET .../blocked-numbers бэкенд уже
  // отклоняет 403-м, без этой проверки страница падает Next.js error
  // overlay вместо редиректа (тот же паттерн, что у /settings//prompts).
  const user = await fetchCurrentUser();
  if (user?.role === "client") {
    redirect(`/bots/${id}`);
  }
  const [bot, numbers] = await Promise.all([
    fetchBot(API_INTERNAL_URL, id),
    fetchBlockedNumbers(API_INTERNAL_URL, id, { limit: BLOCKED_PAGE_SIZE }),
  ]);
  if (!bot) {
    notFound();
  }

  return (
    <main>
      <BlockedNumbersTable
        botId={id}
        apiBaseUrl={API_PROXY_PATH}
        numbers={numbers}
        pageSize={BLOCKED_PAGE_SIZE}
      />
    </main>
  );
}
