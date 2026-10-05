"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { useToast } from "@/components/ToastProvider";
import { Button } from "@/components/ui/Button";
import { Select } from "@/components/ui/Select";
import { patchBotLifecycleStatus, type LifecycleStatus } from "@/lib/api";
import { LIFECYCLE_STATUSES, LIFECYCLE_STATUS_BADGES } from "@/lib/lifecycleStatus";

interface LifecycleStatusFormProps {
  botId: string;
  apiBaseUrl: string;
  initialStatus: LifecycleStatus;
}

// Служебная метка владельца платформы (FEATURES.md 6.22): на работу бота
// не влияет, паузу делает отдельный тумблер "enabled" на Обзоре.
export function LifecycleStatusForm({ botId, apiBaseUrl, initialStatus }: LifecycleStatusFormProps) {
  const router = useRouter();
  const { showError, showSuccess } = useToast();
  const [status, setStatus] = useState<LifecycleStatus>(initialStatus);
  const [saving, setSaving] = useState(false);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    try {
      await patchBotLifecycleStatus(apiBaseUrl, botId, status);
      showSuccess("Статус сохранён");
      router.refresh();
    } catch (err) {
      showError(err instanceof Error ? err.message : "Не удалось сохранить статус");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={(event) => void handleSubmit(event)} className="flex items-center gap-2.5">
      <Select
        value={status}
        onChange={(event) => setStatus(event.target.value as LifecycleStatus)}
        aria-label="Статус клиента"
        className="max-w-sm"
      >
        {LIFECYCLE_STATUSES.map((value) => (
          <option key={value} value={value}>
            {LIFECYCLE_STATUS_BADGES[value].label}
          </option>
        ))}
      </Select>
      <Button type="submit" disabled={saving}>
        {saving ? "Сохраняем…" : "Сохранить"}
      </Button>
    </form>
  );
}
