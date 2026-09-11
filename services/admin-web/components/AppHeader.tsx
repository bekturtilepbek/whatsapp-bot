import Link from "next/link";
import { logout } from "@/app/login/actions";
import { API_INTERNAL_URL } from "@/lib/env";

interface CurrentUser {
  email: string;
  is_platform_owner: boolean;
}

async function fetchCurrentUser(): Promise<CurrentUser | null> {
  const { cookies } = await import("next/headers");
  const token = (await cookies()).get("session")?.value;
  if (!token) return null;
  const res = await fetch(`${API_INTERNAL_URL}/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!res.ok) return null;
  return (await res.json()) as CurrentUser;
}

export async function AppHeader() {
  const user = await fetchCurrentUser();
  if (!user) return null;

  return (
    <header>
      <span>{user.email}</span>
      {user.is_platform_owner && <Link href="/users">Пользователи</Link>}
      <form action={logout}>
        <button type="submit">Выйти</button>
      </form>
    </header>
  );
}
