import { redirect } from "next/navigation";
import { AuditLogTable } from "@/components/AuditLogTable";
import { fetchAuditLog, fetchBots } from "@/lib/api";
import { currentUserIsOwner } from "@/lib/currentUser";
import { API_INTERNAL_URL, API_PROXY_PATH } from "@/lib/env";

const AUDIT_LOG_PAGE_SIZE = 50;

export default async function AuditLogPage() {
  if (!(await currentUserIsOwner())) {
    redirect("/bots");
  }

  const [entries, bots] = await Promise.all([
    fetchAuditLog(API_INTERNAL_URL, { limit: AUDIT_LOG_PAGE_SIZE }),
    fetchBots(API_INTERNAL_URL),
  ]);

  return (
    <main>
      <h1>Аудит-лог</h1>
      <AuditLogTable
        apiBaseUrl={API_PROXY_PATH}
        entries={entries}
        bots={bots}
        pageSize={AUDIT_LOG_PAGE_SIZE}
      />
    </main>
  );
}
