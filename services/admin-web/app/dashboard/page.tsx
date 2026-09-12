import { redirect } from "next/navigation";
import { DashboardTable } from "@/components/DashboardTable";
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
      <h1>Дашборд</h1>
      <DashboardTable bots={bots} />
    </main>
  );
}
