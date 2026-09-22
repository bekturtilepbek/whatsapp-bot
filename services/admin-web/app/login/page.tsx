"use client";

import { useActionState, useEffect, useRef, type FormEvent } from "react";
import { login } from "./actions";
import { useToast } from "@/components/ToastProvider";
import { BrandMark } from "@/components/ui/BrandMark";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { useInvalidShake } from "@/lib/useInvalidShake";

export default function LoginPage() {
  const { showError } = useToast();
  const [error, formAction, pending] = useActionState(login, null);
  // useActionState не даёт номер попытки — если два неудачных сабмита подряд
  // вернут ОДИНАКОВЫЙ текст ошибки, эффект по [error] не перезапустится
  // (значение не изменилось), и вторая неудача останется без toast. Ловим
  // переход pending true→false вместо значения error — так каждый
  // завершённый сабмит с ошибкой показывает свой toast, даже повторный.
  const wasPending = useRef(false);
  const { shake, clear, isInvalid, shakeKey } = useInvalidShake();

  useEffect(() => {
    if (wasPending.current && !pending && error) {
      showError(error);
    }
    wasPending.current = pending;
  }, [pending, error, showError]);

  // Поля остаются неконтролируемыми (форма отправляется через Server
  // Action) — значения читаем из FormData на submit, а не из React state.
  // noValidate отключает нативную валидацию браузера: она молча блокирует
  // submit ДО этого хендлера и ДО formAction — тот же приём, что и в
  // остальных формах кабинета (нативный required тут иначе просто теряется).
  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    const data = new FormData(event.currentTarget);
    const invalidFields: string[] = [];
    if (!String(data.get("email") ?? "").trim()) invalidFields.push("email");
    if (!String(data.get("password") ?? "")) invalidFields.push("password");
    if (invalidFields.length > 0) {
      event.preventDefault();
      shake(invalidFields);
      showError("Введите email и пароль");
    }
  };

  return (
    <main className="flex min-h-full items-center justify-center">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center justify-center gap-2">
          <BrandMark />
          <span className="text-sm font-bold text-ink">Платформа ботов</span>
        </div>
        <Card className="p-8">
          <h1 className="mb-6 text-lg font-semibold text-ink">Вход</h1>
          <form
            noValidate
            action={formAction}
            onSubmit={handleSubmit}
            className="flex flex-col gap-5"
          >
            <label
              className={`mb-0 block text-sm font-medium ${isInvalid("email") ? "text-danger" : "text-ink"}`}
            >
              <div
                key={isInvalid("email") ? `email-shake-${shakeKey}` : "email"}
                className={isInvalid("email") ? "animate-shake" : undefined}
              >
                Email
                <Input
                  type="email"
                  name="email"
                  autoFocus
                  invalid={isInvalid("email")}
                  onChange={() => clear("email")}
                  className="mt-1.5"
                />
              </div>
            </label>
            <label
              className={`mb-0 block text-sm font-medium ${isInvalid("password") ? "text-danger" : "text-ink"}`}
            >
              <div
                key={isInvalid("password") ? `password-shake-${shakeKey}` : "password"}
                className={isInvalid("password") ? "animate-shake" : undefined}
              >
                Пароль
                <Input
                  type="password"
                  name="password"
                  invalid={isInvalid("password")}
                  onChange={() => clear("password")}
                  className="mt-1.5"
                />
              </div>
            </label>
            <Button type="submit" disabled={pending} className="w-full justify-center">
              {pending ? "Входим…" : "Войти"}
            </Button>
          </form>
        </Card>
      </div>
    </main>
  );
}
