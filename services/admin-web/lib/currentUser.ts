// Текущий пользователь на сервере (Server Component) — читает session-cookie
// напрямую и зовёт GET /auth/me по API_INTERNAL_URL (не через apiFetch: этот
// модуль сам вызывается только на сервере, apiFetch's client-side ветка тут
// не нужна). Третье место, где понадобился этот код (Sidebar, /users,
// /bots/new) — вынесено сюда вместо третьей копии (FEATURES.md 6.18/6.20).

import { API_INTERNAL_URL } from "./env";

export interface CurrentUser {
  email: string;
  is_platform_owner: boolean;
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

export async function currentUserIsOwner(): Promise<boolean> {
  const user = await fetchCurrentUser();
  return user?.is_platform_owner ?? false;
}
