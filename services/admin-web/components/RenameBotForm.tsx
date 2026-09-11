"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { patchBotName } from "@/lib/api";

interface RenameBotFormProps {
  botId: string;
  apiBaseUrl: string;
  initialName: string;
}

export function RenameBotForm({ botId, apiBaseUrl, initialName }: RenameBotFormProps) {
  const router = useRouter();
  const [name, setName] = useState(initialName);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim()) {
      setError("Название не может быть пустым");
      return;
    }
    setError(null);
    setSaving(true);
    try {
      await patchBotName(apiBaseUrl, botId, name);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить название");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={(event) => void handleSubmit(event)}>
      <label>
        Название бота
        <input
          type="text"
          value={name}
          onChange={(event) => setName(event.target.value)}
          aria-label="Название бота"
        />
      </label>
      <button type="submit" disabled={saving}>
        {saving ? "Сохраняем…" : "Сохранить"}
      </button>
      {error && (
        <p role="alert" style={{ color: "crimson" }}>
          {error}
        </p>
      )}
    </form>
  );
}
