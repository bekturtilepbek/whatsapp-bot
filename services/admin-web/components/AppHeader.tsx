import Link from "next/link";
import { logout } from "@/app/login/actions";
import { fetchCurrentUser } from "@/lib/currentUser";

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
