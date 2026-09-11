"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { createBot } from "@/lib/api";

interface NewBotFormProps {
  apiBaseUrl: string;
}

export function NewBotForm({ apiBaseUrl }: NewBotFormProps) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim()) {
      return;
    }
    setError(null);
    setCreating(true);
    try {
      const bot = await createBot(apiBaseUrl, name);
      router.push(`/bots/${bot.id}`);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось создать бота");
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
      {error && (
        <p role="alert" style={{ color: "crimson" }}>
          {error}
        </p>
      )}
    </form>
  );
}
