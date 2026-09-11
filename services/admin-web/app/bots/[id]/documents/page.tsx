import Link from "next/link";
import { notFound } from "next/navigation";
import { DocumentsTable } from "@/components/DocumentsTable";
import { fetchBot, fetchDocuments } from "@/lib/api";
import { API_INTERNAL_URL, API_PROXY_PATH } from "@/lib/env";

export default async function BotDocumentsPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const bot = await fetchBot(API_INTERNAL_URL, id);
  if (!bot) {
    notFound();
  }
  const documents = await fetchDocuments(API_INTERNAL_URL, id);

  return (
    <main>
      <p>
        <Link href={`/bots/${id}`}>← Назад к боту</Link>
      </p>
      <h1>{bot.name} — документы</h1>
      <DocumentsTable botId={id} apiBaseUrl={API_PROXY_PATH} documents={documents} />
    </main>
  );
}
