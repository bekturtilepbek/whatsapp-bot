import Link from "next/link";
import { BotsTable } from "@/components/BotsTable";
import { BUTTON_BASE_CLASSES, BUTTON_VARIANT_CLASSES } from "@/components/ui/Button";
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
            <Link
              href="/bots/new"
              className={`${BUTTON_BASE_CLASSES} ${BUTTON_VARIANT_CLASSES.primary}`}
            >
              Создать бота →
            </Link>
          ) : undefined
        }
      />
      <BotsTable bots={bots} />
    </main>
  );
}
