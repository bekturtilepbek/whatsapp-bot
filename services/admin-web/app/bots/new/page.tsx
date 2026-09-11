import Link from "next/link";
import { redirect } from "next/navigation";
import { NewBotForm } from "@/components/NewBotForm";
import { currentUserIsOwner } from "@/lib/currentUser";
import { API_PROXY_PATH } from "@/lib/env";

export default async function NewBotPage() {
  if (!(await currentUserIsOwner())) {
    redirect("/bots");
  }

  return (
    <main>
      <p>
        <Link href="/bots">← Назад к списку</Link>
      </p>
      <h1>Новый бот</h1>
      <NewBotForm apiBaseUrl={API_PROXY_PATH} />
    </main>
  );
}
