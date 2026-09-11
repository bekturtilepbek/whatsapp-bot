"use client";

import { useActionState } from "react";
import { login } from "./actions";

export default function LoginPage() {
  const [error, formAction, pending] = useActionState(login, null);

  return (
    <main>
      <h1>Вход</h1>
      <form action={formAction}>
        <label>
          Email
          <input type="email" name="email" required autoFocus />
        </label>
        <label>
          Пароль
          <input type="password" name="password" required />
        </label>
        {error && (
          <p role="alert" style={{ color: "crimson" }}>
            {error}
          </p>
        )}
        <button type="submit" disabled={pending}>
          {pending ? "Входим…" : "Войти"}
        </button>
      </form>
    </main>
  );
}
