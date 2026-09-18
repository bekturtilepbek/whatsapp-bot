"use client";

import { useActionState, useEffect, useRef } from "react";
import { login } from "./actions";
import { useToast } from "@/components/ToastProvider";
import { BrandMark } from "@/components/ui/BrandMark";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";

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
    <main className="flex min-h-full items-center justify-center">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center justify-center gap-2">
          <BrandMark />
          <span className="text-sm font-bold text-ink">Платформа ботов</span>
        </div>
        <Card className="p-8">
          <h1 className="mb-6 text-lg font-semibold text-ink">Вход</h1>
          <form action={formAction} className="flex flex-col gap-5">
            <label className="mb-0 block text-sm font-medium text-ink">
              Email
              <Input type="email" name="email" required autoFocus className="mt-1.5" />
            </label>
            <label className="mb-0 block text-sm font-medium text-ink">
              Пароль
              <Input type="password" name="password" required className="mt-1.5" />
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
