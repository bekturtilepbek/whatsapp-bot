import { BotsTable } from "@/components/BotsTable";
import { fetchBots } from "@/lib/api";
import { API_INTERNAL_URL } from "@/lib/env";

export default async function BotsPage() {
  const bots = await fetchBots(API_INTERNAL_URL);

  return (
    <main>
      <h1>Боты</h1>
      <BotsTable bots={bots} />
    </main>
  );
}
