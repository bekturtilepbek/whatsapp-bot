"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { createBot, type PrompterBrief } from "@/lib/api";
import { useToast } from "@/components/ToastProvider";
import { useInvalidShake } from "@/lib/useInvalidShake";

interface NewBotFormProps {
  apiBaseUrl: string;
  /** Только роль prompter (FEATURES.md 6.18) — GET /users/prompters.
   * Пустой массив — секция "Ответственный" не рендерится вовсе (нечего
   * выбирать, кроме единственной опции "Не назначен"). */
  prompters: PrompterBrief[];
}

const UNASSIGNED = "";

export function NewBotForm({ apiBaseUrl, prompters }: NewBotFormProps) {
  const router = useRouter();
  const { showError, showSuccess } = useToast();
  const [name, setName] = useState("");
  const [responsibleUserId, setResponsibleUserId] = useState(UNASSIGNED);
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
      const bot = await createBot(
        apiBaseUrl,
        name,
        responsibleUserId === UNASSIGNED ? null : responsibleUserId,
      );
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
      {prompters.length > 0 && (
        <label className="mb-4 block text-sm font-medium text-ink">
          Ответственный (необязательно)
          <Select
            value={responsibleUserId}
            onChange={(event) => setResponsibleUserId(event.target.value)}
            className="mt-1.5"
          >
            <option value={UNASSIGNED}>Не назначен</option>
            {prompters.map((p) => (
              <option key={p.id} value={p.id}>
                {p.email}
              </option>
            ))}
          </Select>
        </label>
      )}
      <Button type="submit" disabled={creating}>
        {creating ? "Создаём…" : "Создать"}
      </Button>
    </form>
  );
}
