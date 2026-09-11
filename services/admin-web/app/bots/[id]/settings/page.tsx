import Link from "next/link";
import { notFound } from "next/navigation";
import { BotSettingsForm } from "@/components/BotSettingsForm";
import { RenameBotForm } from "@/components/RenameBotForm";
import { DEFAULT_BOT_SETTINGS, fetchBot } from "@/lib/api";
import { API_INTERNAL_URL, API_PROXY_PATH } from "@/lib/env";

export default async function BotSettingsPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const bot = await fetchBot(API_INTERNAL_URL, id);
  if (!bot) {
    notFound();
  }

  const initialSettings = { ...DEFAULT_BOT_SETTINGS, ...bot.settings };

  return (
    <main>
      <p>
        <Link href={`/bots/${id}`}>← Назад к боту</Link>
      </p>
      <h1>{bot.name} — настройки</h1>
      <RenameBotForm botId={id} apiBaseUrl={API_PROXY_PATH} initialName={bot.name} />
      <BotSettingsForm botId={id} apiBaseUrl={API_PROXY_PATH} initialSettings={initialSettings} />
    </main>
  );
}
