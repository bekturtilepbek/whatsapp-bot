import { notFound } from "next/navigation";
import { SandboxChat } from "@/components/SandboxChat";
import { fetchBot } from "@/lib/api";
import { API_INTERNAL_URL, API_PROXY_PATH } from "@/lib/env";

// Доступна всем ролям с доступом к боту (FEATURES.md 6.18 ролевой
// пересмотр 2026-09-22 — раньше owner-only) — гейт теперь только на
// бэкенде (require_bot_access), как у остальных вкладок бота.
export default async function SandboxPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const bot = await fetchBot(API_INTERNAL_URL, id);
  if (!bot) {
    notFound();
  }

  return (
    <main>
      <SandboxChat apiBaseUrl={API_PROXY_PATH} botId={bot.id} botName={bot.name} />
    </main>
  );
}
