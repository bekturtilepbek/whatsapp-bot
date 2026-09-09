import { notFound } from "next/navigation";
import { QrPanel } from "@/components/QrPanel";
import { fetchBot } from "@/lib/api";

const API_INTERNAL_URL = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
const API_PUBLIC_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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
      <QrPanel initialBot={bot} apiBaseUrl={API_PUBLIC_URL} />
    </main>
  );
}
