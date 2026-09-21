import { notFound } from "next/navigation";
import { ActiveChatsTable } from "@/components/ActiveChatsTable";
import { fetchActiveChats, fetchBot } from "@/lib/api";
import { API_INTERNAL_URL, API_PROXY_PATH } from "@/lib/env";

export default async function BotActiveChatsPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const [bot, chats] = await Promise.all([
    fetchBot(API_INTERNAL_URL, id),
    fetchActiveChats(API_INTERNAL_URL, id),
  ]);
  if (!bot) {
    notFound();
  }

  return (
    <main>
      <ActiveChatsTable botId={id} apiBaseUrl={API_PROXY_PATH} initialChats={chats} />
    </main>
  );
}
