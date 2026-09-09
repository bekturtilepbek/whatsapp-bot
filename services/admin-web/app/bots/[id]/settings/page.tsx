import Link from "next/link";
import { notFound } from "next/navigation";
import { BotSettingsForm } from "@/components/BotSettingsForm";
import { DEFAULT_BOT_SETTINGS, fetchBot } from "@/lib/api";

const API_INTERNAL_URL = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
const API_PUBLIC_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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
      <BotSettingsForm botId={id} apiBaseUrl={API_PUBLIC_URL} initialSettings={initialSettings} />
    </main>
  );
}
