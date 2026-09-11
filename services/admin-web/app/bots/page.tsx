import Link from "next/link";
import { BotsTable } from "@/components/BotsTable";
import { fetchBots } from "@/lib/api";
import { currentUserIsOwner } from "@/lib/currentUser";
import { API_INTERNAL_URL } from "@/lib/env";

export default async function BotsPage() {
  const [bots, isOwner] = await Promise.all([fetchBots(API_INTERNAL_URL), currentUserIsOwner()]);

  return (
    <main>
      <h1>Боты</h1>
      {isOwner && (
        <p>
          <Link href="/bots/new">Создать бота →</Link>
        </p>
      )}
      <BotsTable bots={bots} />
    </main>
  );
}
