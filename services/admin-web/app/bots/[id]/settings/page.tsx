import { notFound } from "next/navigation";
import { BotSettingsForm } from "@/components/BotSettingsForm";
import { RenameBotForm } from "@/components/RenameBotForm";
import { TelegramLeadToolForm } from "@/components/TelegramLeadToolForm";
import { Card } from "@/components/ui/Card";
import { DEFAULT_BOT_SETTINGS, fetchBot, fetchBotTools } from "@/lib/api";
import { API_INTERNAL_URL, API_PROXY_PATH } from "@/lib/env";

export default async function BotSettingsPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const [bot, tools] = await Promise.all([
    fetchBot(API_INTERNAL_URL, id),
    fetchBotTools(API_INTERNAL_URL, id),
  ]);
  if (!bot) {
    notFound();
  }

  const initialSettings = { ...DEFAULT_BOT_SETTINGS, ...bot.settings };
  const telegramLeadBinding = tools.find((t) => t.tool_name === "send_telegram_lead") ?? null;

  return (
    <main className="space-y-5">
      <Card className="p-5">
        <h2 className="mb-4 text-[15px] font-semibold text-ink">Название</h2>
        <RenameBotForm botId={id} apiBaseUrl={API_PROXY_PATH} initialName={bot.name} />
      </Card>
      <BotSettingsForm botId={id} apiBaseUrl={API_PROXY_PATH} initialSettings={initialSettings} />
      <TelegramLeadToolForm
        botId={id}
        apiBaseUrl={API_PROXY_PATH}
        initialBinding={telegramLeadBinding}
      />
    </main>
  );
}
