import { notFound, redirect } from "next/navigation";
import { SandboxChat } from "@/components/SandboxChat";
import { fetchBot } from "@/lib/api";
import { currentUserIsOwner } from "@/lib/currentUser";
import { API_INTERNAL_URL, API_PROXY_PATH } from "@/lib/env";

export default async function SandboxPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!(await currentUserIsOwner())) {
    redirect(`/bots/${id}`);
  }

  const bot = await fetchBot(API_INTERNAL_URL, id);
  if (!bot) {
    notFound();
  }

  return (
    <main>
      <h1>Песочница</h1>
      <SandboxChat apiBaseUrl={API_PROXY_PATH} botId={bot.id} botName={bot.name} />
    </main>
  );
}
