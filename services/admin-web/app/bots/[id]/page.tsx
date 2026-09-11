import Link from "next/link";
import { notFound } from "next/navigation";
import { QrPanel } from "@/components/QrPanel";
import { fetchBot } from "@/lib/api";
import { API_INTERNAL_URL, API_PROXY_PATH } from "@/lib/env";

export default async function BotPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const bot = await fetchBot(API_INTERNAL_URL, id);
  if (!bot) {
    notFound();
  }

  return (
    <main>
      <h1>{bot.name}</h1>
      <p>
        <Link href={`/bots/${bot.id}/prompts`}>Промпты и история →</Link>
      </p>
      <p>
        <Link href={`/bots/${bot.id}/settings`}>Настройки →</Link>
      </p>
      <p>
        <Link href={`/bots/${bot.id}/products`}>Товары →</Link>
      </p>
      <p>
        <Link href={`/bots/${bot.id}/blocked-numbers`}>Чёрный список →</Link>
      </p>
      <p>
        <Link href={`/bots/${bot.id}/documents`}>Документы →</Link>
      </p>
      <QrPanel initialBot={bot} apiBaseUrl={API_PROXY_PATH} />
    </main>
  );
}
