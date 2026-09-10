import Link from "next/link";
import { notFound } from "next/navigation";
import { PromptEditor } from "@/components/PromptEditor";
import { fetchBot, fetchPromptVersions } from "@/lib/api";
import { API_INTERNAL_URL, API_PROXY_PATH } from "@/lib/env";

export default async function BotPromptsPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const bot = await fetchBot(API_INTERNAL_URL, id);
  if (!bot) {
    notFound();
  }

  const [mainVersions, imageVersions, pdfVersions] = await Promise.all([
    fetchPromptVersions(API_INTERNAL_URL, id, "main"),
    fetchPromptVersions(API_INTERNAL_URL, id, "image"),
    fetchPromptVersions(API_INTERNAL_URL, id, "pdf"),
  ]);

  return (
    <main>
      <p>
        <Link href={`/bots/${id}`}>← Назад к боту</Link>
      </p>
      <h1>{bot.name} — промпты</h1>
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
