"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { API_INTERNAL_URL } from "@/lib/env";

const SESSION_COOKIE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60;

export async function login(_prevState: string | null, formData: FormData): Promise<string | null> {
  const email = String(formData.get("email") ?? "");
  const password = String(formData.get("password") ?? "");

  const res = await fetch(`${API_INTERNAL_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });

  if (!res.ok) {
    return "Неверный email или пароль";
  }

  const body = (await res.json()) as { token: string };
  (await cookies()).set("session", body.token, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    maxAge: SESSION_COOKIE_MAX_AGE_SECONDS,
    path: "/",
  });

  redirect("/bots");
}

export async function logout(): Promise<void> {
  (await cookies()).delete("session");
  redirect("/login");
}
