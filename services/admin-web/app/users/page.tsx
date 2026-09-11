import { redirect } from "next/navigation";
import { UsersTable } from "@/components/UsersTable";
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

  return (
    <main>
      <h1>Пользователи</h1>
      <UsersTable apiBaseUrl={API_PROXY_PATH} users={users} bots={bots} />
    </main>
  );
}
