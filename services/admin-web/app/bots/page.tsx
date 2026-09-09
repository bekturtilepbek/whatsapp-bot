import { BotsTable } from "@/components/BotsTable";
import { fetchBots } from "@/lib/api";

const API_INTERNAL_URL = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

export default async function BotsPage() {
  const bots = await fetchBots(API_INTERNAL_URL);

  return (
    <main>
      <h1>Боты</h1>
      <BotsTable bots={bots} />
    </main>
  );
}
