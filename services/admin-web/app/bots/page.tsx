import Link from "next/link";
import { BotsSearch } from "@/components/BotsSearch";
import { buttonClasses } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { fetchBots } from "@/lib/api";
import { currentUserIsOwner } from "@/lib/currentUser";
import { API_INTERNAL_URL } from "@/lib/env";

export default async function BotsPage() {
  const [bots, isOwner] = await Promise.all([fetchBots(API_INTERNAL_URL), currentUserIsOwner()]);

  return (
    <main>
      <PageHeader
        title="Боты"
        subtitle={`Ботов: ${bots.length}`}
        action={
          isOwner ? (
            <Link href="/bots/new" className={buttonClasses()}>
              Создать бота →
            </Link>
          ) : undefined
        }
      />
      <BotsSearch bots={bots} />
    </main>
  );
}
