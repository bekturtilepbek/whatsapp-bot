import { redirect } from "next/navigation";
import { DashboardTable } from "@/components/DashboardTable";
import { PageHeader } from "@/components/ui/PageHeader";
import { fetchBots } from "@/lib/api";
import { currentUserIsOwner } from "@/lib/currentUser";
import { API_INTERNAL_URL } from "@/lib/env";

export default async function DashboardPage() {
  if (!(await currentUserIsOwner())) {
    redirect("/bots");
  }

  const bots = await fetchBots(API_INTERNAL_URL);

  return (
    <main>
      <PageHeader title="Дашборд" subtitle={`Ботов: ${bots.length}`} />
      <DashboardTable bots={bots} />
    </main>
  );
}
