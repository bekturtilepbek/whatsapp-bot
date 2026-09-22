"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/Button";
import { Select } from "@/components/ui/Select";
import { patchBotResponsibleUser, type PrompterBrief } from "@/lib/api";
import { useToast } from "@/components/ToastProvider";

interface ResponsibleUserFormProps {
  botId: string;
  apiBaseUrl: string;
  initialResponsibleUserId: string | null;
  prompters: PrompterBrief[];
}

const UNASSIGNED = "";

// PATCH /bots/{id} не отзывает грант у прежнего ответственного при смене
// (осознанно — см. план 2026-09-22): переназначение и отзыв доступа —
// разные действия, второе делается явно через /users.
export function ResponsibleUserForm({
  botId,
  apiBaseUrl,
  initialResponsibleUserId,
  prompters,
}: ResponsibleUserFormProps) {
  const router = useRouter();
  const { showError, showSuccess } = useToast();
  const [responsibleUserId, setResponsibleUserId] = useState(
    initialResponsibleUserId ?? UNASSIGNED,
  );
  const [saving, setSaving] = useState(false);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    try {
      await patchBotResponsibleUser(
        apiBaseUrl,
        botId,
        responsibleUserId === UNASSIGNED ? null : responsibleUserId,
      );
      showSuccess("Ответственный сохранён");
      router.refresh();
    } catch (err) {
      showError(err instanceof Error ? err.message : "Не удалось сохранить ответственного");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={(event) => void handleSubmit(event)} className="flex items-center gap-2.5">
      {/* Без видимой <label>-подписи — заголовок карточки уже описывает
          единственное поле формы (см. app/bots/[id]/settings/page.tsx),
          тот же паттерн, что у RenameBotForm. */}
      <Select
        value={responsibleUserId}
        onChange={(event) => setResponsibleUserId(event.target.value)}
        aria-label="Ответственный"
        className="max-w-sm"
      >
        <option value={UNASSIGNED}>Не назначен</option>
        {prompters.map((p) => (
          <option key={p.id} value={p.id}>
            {p.email}
          </option>
        ))}
      </Select>
      <Button type="submit" disabled={saving}>
        {saving ? "Сохраняем…" : "Сохранить"}
      </Button>
    </form>
  );
}
