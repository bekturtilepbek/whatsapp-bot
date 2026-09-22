// Текущий пользователь на сервере (Server Component) — читает session-cookie
// напрямую и зовёт GET /auth/me по API_INTERNAL_URL (не через apiFetch: этот
// модуль сам вызывается только на сервере, apiFetch's client-side ветка тут
// не нужна). Третье место, где понадобился этот код (Sidebar, /users,
// /bots/new) — вынесено сюда вместо третьей копии (FEATURES.md 6.18/6.20).

import { API_INTERNAL_URL } from "./env";

export type UserRole = "superadmin" | "admin" | "prompter" | "client";

// superadmin/admin видят все боты без грантов и платформенные разделы
// (кроме "Пользователи" — только superadmin, см. app/users/page.tsx).
export const PLATFORM_WIDE_ROLES: readonly UserRole[] = ["superadmin", "admin"];

export interface CurrentUser {
  email: string;
  role: UserRole;
}

export async function fetchCurrentUser(): Promise<CurrentUser | null> {
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

export async function currentUserIsPlatformWide(): Promise<boolean> {
  const user = await fetchCurrentUser();
  return user !== null && PLATFORM_WIDE_ROLES.includes(user.role);
}

export async function currentUserIsSuperadmin(): Promise<boolean> {
  const user = await fetchCurrentUser();
  return user?.role === "superadmin";
}
