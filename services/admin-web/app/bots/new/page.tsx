import Link from "next/link";
import { redirect } from "next/navigation";
import { NewBotForm } from "@/components/NewBotForm";
import { Card } from "@/components/ui/Card";
import { PageHeader } from "@/components/ui/PageHeader";
import { fetchPrompters } from "@/lib/api";
import { currentUserIsPlatformWide } from "@/lib/currentUser";
import { API_INTERNAL_URL, API_PROXY_PATH } from "@/lib/env";

export default async function NewBotPage() {
  if (!(await currentUserIsPlatformWide())) {
    redirect("/bots");
  }
  const prompters = await fetchPrompters(API_INTERNAL_URL);

  return (
    <main>
      <Link href="/bots" className="text-sm text-ink-soft hover:text-ink">
        Назад к списку
      </Link>
      <PageHeader title="Новый бот" />
      <Card className="max-w-sm p-5">
        <NewBotForm apiBaseUrl={API_PROXY_PATH} prompters={prompters} />
      </Card>
    </main>
  );
}
