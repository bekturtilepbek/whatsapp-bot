import { redirect } from "next/navigation";
import { UsersTable } from "@/components/UsersTable";
import { PageHeader } from "@/components/ui/PageHeader";
import { fetchBots, fetchUsers } from "@/lib/api";
import { currentUserIsSuperadmin } from "@/lib/currentUser";
import { API_INTERNAL_URL, API_PROXY_PATH } from "@/lib/env";

export default async function UsersPage() {
  // Только суперадмин — Admin намеренно НЕ управляет пользователями
  // (единственное, что отличает его от Superadmin, FEATURES.md 6.18
  // ролевой пересмотр 2026-09-22).
  if (!(await currentUserIsSuperadmin())) {
    redirect("/bots");
  }

  const [users, bots] = await Promise.all([
    fetchUsers(API_INTERNAL_URL),
    fetchBots(API_INTERNAL_URL),
  ]);
  const nonSuperadminCount = users.filter((u) => u.role !== "superadmin").length;

  return (
    <main>
      <PageHeader title="Пользователи" subtitle={`Пользователей: ${nonSuperadminCount}`} />
      <UsersTable apiBaseUrl={API_PROXY_PATH} users={users} bots={bots} />
    </main>
  );
}
