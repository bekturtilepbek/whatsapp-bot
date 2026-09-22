"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { patchBotName } from "@/lib/api";
import { useToast } from "@/components/ToastProvider";

interface RenameBotFormProps {
  botId: string;
  apiBaseUrl: string;
  initialName: string;
}

export function RenameBotForm({ botId, apiBaseUrl, initialName }: RenameBotFormProps) {
  const router = useRouter();
  const { showError, showSuccess } = useToast();
  const [name, setName] = useState(initialName);
  const [saving, setSaving] = useState(false);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim()) {
      showError("Название не может быть пустым");
      return;
    }
    setSaving(true);
    try {
      await patchBotName(apiBaseUrl, botId, name);
      showSuccess("Название сохранено");
      router.refresh();
    } catch (err) {
      showError(err instanceof Error ? err.message : "Не удалось сохранить название");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={(event) => void handleSubmit(event)} className="flex items-center gap-2.5">
      {/* Без видимой <label>-подписи — заголовок карточки "Название" (см.
          app/bots/[id]/settings/page.tsx) уже описывает единственное поле
          формы, вторая подпись рядом была бы дублирующей. aria-label
          сохраняет доступность для скринридеров. */}
      <Input
        type="text"
        value={name}
        onChange={(event) => setName(event.target.value)}
        aria-label="Название бота"
        className="max-w-sm"
      />
      <Button type="submit" disabled={saving}>
        {saving ? "Сохраняем…" : "Сохранить"}
      </Button>
    </form>
  );
}
