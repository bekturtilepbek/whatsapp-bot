import { redirect } from "next/navigation";
import { UsersTable } from "@/components/UsersTable";
import { PageHeader } from "@/components/ui/PageHeader";
import { fetchBots, fetchUsers } from "@/lib/api";
import { currentUserIsOwner } from "@/lib/currentUser";
import { API_INTERNAL_URL, API_PROXY_PATH } from "@/lib/env";

export default async function UsersPage() {
  if (!(await currentUserIsOwner())) {
    redirect("/bots");
  }

  const [users, bots] = await Promise.all([
    fetchUsers(API_INTERNAL_URL),
    fetchBots(API_INTERNAL_URL),
  ]);
  const clientCount = users.filter((u) => !u.is_platform_owner).length;

  return (
    <main>
      <PageHeader title="Пользователи" subtitle={`Пользователей: ${clientCount}`} />
      <UsersTable apiBaseUrl={API_PROXY_PATH} users={users} bots={bots} />
    </main>
  );
}
