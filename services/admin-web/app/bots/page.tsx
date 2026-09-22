import Link from "next/link";
import { BotsSearch } from "@/components/BotsSearch";
import { buttonClasses } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { fetchBots } from "@/lib/api";
import { currentUserIsPlatformWide } from "@/lib/currentUser";
import { API_INTERNAL_URL } from "@/lib/env";

export default async function BotsPage() {
  const [bots, canCreateBots] = await Promise.all([
    fetchBots(API_INTERNAL_URL),
    currentUserIsPlatformWide(),
  ]);

  return (
    <main>
      <PageHeader
        title="Боты"
        subtitle={`Ботов: ${bots.length}`}
        action={
          canCreateBots ? (
            <Link href="/bots/new" className={buttonClasses()}>
              Создать бота
            </Link>
          ) : undefined
        }
      />
      <BotsSearch bots={bots} />
    </main>
  );
}
