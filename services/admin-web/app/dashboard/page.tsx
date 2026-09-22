import { redirect } from "next/navigation";
import { DashboardTable } from "@/components/DashboardTable";
import { PageHeader } from "@/components/ui/PageHeader";
import { fetchBots } from "@/lib/api";
import { currentUserIsPlatformWide } from "@/lib/currentUser";
import { API_INTERNAL_URL } from "@/lib/env";

export default async function DashboardPage() {
  if (!(await currentUserIsPlatformWide())) {
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
