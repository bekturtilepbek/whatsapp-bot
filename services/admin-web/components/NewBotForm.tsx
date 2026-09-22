"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { createBot } from "@/lib/api";
import { useToast } from "@/components/ToastProvider";
import { useInvalidShake } from "@/lib/useInvalidShake";

interface NewBotFormProps {
  apiBaseUrl: string;
}

export function NewBotForm({ apiBaseUrl }: NewBotFormProps) {
  const router = useRouter();
  const { showError, showSuccess } = useToast();
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const { shake, clear, isInvalid, shakeKey } = useInvalidShake();

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim()) {
      showError("Введите имя бота");
      shake(["name"]);
      return;
    }
    setCreating(true);
    try {
      const bot = await createBot(apiBaseUrl, name);
      showSuccess("Бот создан");
      router.push(`/bots/${bot.id}`);
      router.refresh();
    } catch (err) {
      showError(err instanceof Error ? err.message : "Не удалось создать бота");
      setCreating(false);
    }
  };

  return (
    <form onSubmit={(event) => void handleSubmit(event)}>
      <label className={`mb-4 block text-sm font-medium ${isInvalid("name") ? "text-danger" : "text-ink"}`}>
        <div
          key={isInvalid("name") ? `name-shake-${shakeKey}` : "name"}
          className={isInvalid("name") ? "animate-shake" : undefined}
        >
          Имя
          <Input
            type="text"
            value={name}
            onChange={(event) => {
              setName(event.target.value);
              clear("name");
            }}
            placeholder="Название бота"
            aria-label="Имя"
            invalid={isInvalid("name")}
            autoFocus
            className="mt-1.5"
          />
        </div>
      </label>
      <Button type="submit" disabled={creating}>
        {creating ? "Создаём…" : "Создать"}
      </Button>
    </form>
  );
}
