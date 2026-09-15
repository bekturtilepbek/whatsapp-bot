import { redirect } from "next/navigation";
import { UsageTable } from "@/components/UsageTable";
import { PageHeader } from "@/components/ui/PageHeader";
import { fetchUsage, type UsagePeriod } from "@/lib/api";
import { currentUserIsOwner } from "@/lib/currentUser";
import { API_INTERNAL_URL, API_PROXY_PATH } from "@/lib/env";

const DEFAULT_PERIOD: UsagePeriod = "30d";

export default async function UsagePage() {
  if (!(await currentUserIsOwner())) {
    redirect("/bots");
  }

  const summaries = await fetchUsage(API_INTERNAL_URL, DEFAULT_PERIOD);

  return (
    <main>
      <PageHeader title="Расходы OpenAI" />
      <UsageTable apiBaseUrl={API_PROXY_PATH} summaries={summaries} initialPeriod={DEFAULT_PERIOD} />
    </main>
  );
}
