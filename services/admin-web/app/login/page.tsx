"use client";

import { useActionState, useEffect, useRef } from "react";
import { login } from "./actions";
import { useToast } from "@/components/ToastProvider";

export default function LoginPage() {
  const { showError } = useToast();
  const [error, formAction, pending] = useActionState(login, null);
  // useActionState не даёт номер попытки — если два неудачных сабмита подряд
  // вернут ОДИНАКОВЫЙ текст ошибки, эффект по [error] не перезапустится
  // (значение не изменилось), и вторая неудача останется без toast. Ловим
  // переход pending true→false вместо значения error — так каждый
  // завершённый сабмит с ошибкой показывает свой toast, даже повторный.
  const wasPending = useRef(false);

  useEffect(() => {
    if (wasPending.current && !pending && error) {
      showError(error);
    }
    wasPending.current = pending;
  }, [pending, error, showError]);

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
        <button type="submit" disabled={pending}>
          {pending ? "Входим…" : "Войти"}
        </button>
      </form>
    </main>
  );
}
