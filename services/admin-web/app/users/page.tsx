import { redirect } from "next/navigation";
import { UsersTable } from "@/components/UsersTable";
import { fetchBots, fetchUsers } from "@/lib/api";
import { API_INTERNAL_URL, API_PROXY_PATH } from "@/lib/env";

async function currentUserIsOwner(): Promise<boolean> {
  const { cookies } = await import("next/headers");
  const token = (await cookies()).get("session")?.value;
  if (!token) return false;
  const res = await fetch(`${API_INTERNAL_URL}/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!res.ok) return false;
  const user = (await res.json()) as { is_platform_owner: boolean };
  return user.is_platform_owner;
}

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
