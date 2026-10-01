"use server";

import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";
import { API_INTERNAL_URL } from "@/lib/env";

const SESSION_COOKIE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60;
const TOO_MANY_ATTEMPTS_FALLBACK = "Слишком много попыток входа. Попробуйте позже.";

// api отвечает на 429 готовым русским текстом со сроком ожидания ("...через
// 12 мин.") — показываем его как есть. Нечитаемое тело (прокси подменил ответ)
// — общий текст: главное, чтобы человек не принял блокировку за неверный пароль.
async function rateLimitMessage(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body.detail === "string" && body.detail) return body.detail;
  } catch {
    // тело не JSON — ниже общий текст
  }
  return TOO_MANY_ATTEMPTS_FALLBACK;
}

export async function login(_prevState: string | null, formData: FormData): Promise<string | null> {
  const email = String(formData.get("email") ?? "");
  const password = String(formData.get("password") ?? "");

  // api видит только контейнер admin-web, а лимит попыток входа считается и по
  // IP клиента — пробрасываем X-Forwarded-For, который выставил Caddy (он
  // перезаписывает то, что прислал сам клиент).
  const forwardedFor = (await headers()).get("x-forwarded-for");

  const res = await fetch(`${API_INTERNAL_URL}/auth/login`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(forwardedFor ? { "X-Forwarded-For": forwardedFor } : {}),
    },
    body: JSON.stringify({ email, password }),
  });

  if (res.status === 429) {
    return rateLimitMessage(res);
  }
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
