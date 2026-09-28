"use client";

import { useState } from "react";
import { fetchPromptVersions, patchBotPrompt, type PromptKind, type PromptVersion } from "@/lib/api";
import { formatBishkekDateTime } from "@/lib/formatDate";
import { useToast } from "@/components/ToastProvider";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Modal } from "@/components/ui/Modal";
import { Textarea } from "@/components/ui/Textarea";

interface PromptEditorProps {
  botId: string;
  apiBaseUrl: string;
  kind: PromptKind;
  label: string;
  initialBody: string | null;
  initialVersions: PromptVersion[];
}

// Строки короче этого порога не нуждаются в сворачивании — превью и полный
// текст совпадали бы, кнопка "Показать полностью" была бы бессмысленной.
const PREVIEW_LENGTH = 200;

export function PromptEditor({
  botId,
  apiBaseUrl,
  kind,
  label,
  initialBody,
  initialVersions,
}: PromptEditorProps) {
  const { showError, showSuccess } = useToast();
  const [body, setBody] = useState(initialBody ?? "");
  const [versions, setVersions] = useState<PromptVersion[]>(initialVersions);
  const [saving, setSaving] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  // Какие версии в открытой модалке сейчас показаны полностью (не только
  // превью) — по id, чтобы разворачивать каждую версию независимо.
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const save = async (newBody: string) => {
    setSaving(true);
    try {
      await patchBotPrompt(apiBaseUrl, botId, kind, newBody);
      setBody(newBody);
      const updated = await fetchPromptVersions(apiBaseUrl, botId, kind);
      setVersions(updated);
      showSuccess("Сохранено");
    } catch (err) {
      showError(err instanceof Error ? err.message : "Не удалось сохранить");
    } finally {
      setSaving(false);
    }
  };

  const toggleExpanded = (id: string) => {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  return (
    <div className="space-y-5">
      <Card className="p-5">
        <h2 className="mb-4 text-[15px] font-semibold text-ink">{label}</h2>
        <Textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          rows={6}
          aria-label={label}
        />
        <p className="mt-1.5 text-xs text-ink-soft">{body.length} символов</p>
        <div className="mt-3 flex items-center gap-4">
          <Button onClick={() => void save(body)} disabled={saving}>
            {saving ? "Сохраняем…" : "Сохранить"}
          </Button>
          {versions.length > 0 && (
            <button
              type="button"
              onClick={() => setHistoryOpen(true)}
              className="text-sm font-medium text-accent hover:underline"
            >
              История изменений ({versions.length})
            </button>
          )}
        </div>
      </Card>

      <Modal
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        title={`История изменений — ${label}`}
        widthClassName="max-w-2xl"
      >
        <div className="flex flex-col divide-y divide-border">
          {versions.map((version) => {
            const text = version.body ?? "";
            const isExpanded = expanded.has(version.id);
            const isLong = text.length > PREVIEW_LENGTH;
            return (
              <div key={version.id} className="py-3 first:pt-0 last:pb-0">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-xs text-ink-soft">
                    <span className="font-mono">{formatBishkekDateTime(version.created_at)}</span>
                    {" · "}
                    {version.author}
                    {" · "}
                    {text.length} символов
                  </p>
                  <Button
                    variant="secondary"
                    onClick={() => void save(text)}
                    disabled={saving}
                  >
                    Откатить
                  </Button>
                </div>
                <p className="mt-1.5 whitespace-pre-wrap text-sm text-ink">
                  {isExpanded || !isLong ? text : `${text.slice(0, PREVIEW_LENGTH)}…`}
                </p>
                {isLong && (
                  <button
                    type="button"
                    onClick={() => toggleExpanded(version.id)}
                    className="mt-1 text-xs font-medium text-accent hover:underline"
                  >
                    {isExpanded ? "Свернуть" : "Показать полностью"}
                  </button>
                )}
              </div>
            );
          })}
        </div>
      </Modal>
    </div>
  );
}
