import { notFound, redirect } from "next/navigation";
import { PromptEditor } from "@/components/PromptEditor";
import { fetchBot, fetchPromptVersions } from "@/lib/api";
import { fetchCurrentUser } from "@/lib/currentUser";
import { API_INTERNAL_URL, API_PROXY_PATH } from "@/lib/env";

export default async function BotPromptsPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  // client урезан (FullBotAccess) — чтение версий промптов бэкенд бы
  // пропустил, но сохранение (PromptEditor → PATCH .../prompts) уже нет;
  // вкладка вообще не должна быть доступна client, поэтому редиректим
  // сразу, не дожидаясь попытки сохранить (тот же паттерн, что у /settings).
  const user = await fetchCurrentUser();
  if (user?.role === "client") {
    redirect(`/bots/${id}`);
  }
  const [bot, mainVersions, imageVersions, pdfVersions] = await Promise.all([
    fetchBot(API_INTERNAL_URL, id),
    fetchPromptVersions(API_INTERNAL_URL, id, "main"),
    fetchPromptVersions(API_INTERNAL_URL, id, "image"),
    fetchPromptVersions(API_INTERNAL_URL, id, "pdf"),
  ]);
  if (!bot) {
    notFound();
  }

  return (
    <main className="space-y-10">
      <PromptEditor
        botId={id}
        apiBaseUrl={API_PROXY_PATH}
        kind="main"
        label="Основной промпт"
        initialBody={bot.system_prompt}
        initialVersions={mainVersions}
      />
      <PromptEditor
        botId={id}
        apiBaseUrl={API_PROXY_PATH}
        kind="image"
        label="Промпт для фото"
        initialBody={bot.image_prompt}
        initialVersions={imageVersions}
      />
      <PromptEditor
        botId={id}
        apiBaseUrl={API_PROXY_PATH}
        kind="pdf"
        label="Промпт для PDF"
        initialBody={bot.pdf_prompt}
        initialVersions={pdfVersions}
      />
    </main>
  );
}
