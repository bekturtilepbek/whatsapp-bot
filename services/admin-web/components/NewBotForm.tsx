"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { createBot } from "@/lib/api";
import { useToast } from "@/components/ToastProvider";

interface NewBotFormProps {
  apiBaseUrl: string;
}

export function NewBotForm({ apiBaseUrl }: NewBotFormProps) {
  const router = useRouter();
  const { showError, showSuccess } = useToast();
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim()) {
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
      <label>
        Имя
        <input
          type="text"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Название бота"
          aria-label="Имя"
          autoFocus
        />
      </label>
      <button type="submit" disabled={creating}>
        {creating ? "Создаём…" : "Создать"}
      </button>
    </form>
  );
}
