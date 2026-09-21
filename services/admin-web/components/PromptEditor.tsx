"use client";

import { useState } from "react";
import { fetchPromptVersions, patchBotPrompt, type PromptKind, type PromptVersion } from "@/lib/api";
import { formatBishkekDateTime } from "@/lib/formatDate";
import { useToast } from "@/components/ToastProvider";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Table } from "@/components/ui/Table";
import { Textarea } from "@/components/ui/Textarea";

interface PromptEditorProps {
  botId: string;
  apiBaseUrl: string;
  kind: PromptKind;
  label: string;
  initialBody: string | null;
  initialVersions: PromptVersion[];
}

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
  const [showHistory, setShowHistory] = useState(false);

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

  return (
    <div className="space-y-5">
      <Card className="p-5">
        <h2 className="mb-4 text-[15px] font-semibold text-ink">{label}</h2>
        <label className="mb-0 block text-sm font-medium text-ink">
          Текст промпта
          <Textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={6}
            className="mt-1.5"
          />
        </label>
        <div className="mt-3">
          <Button onClick={() => void save(body)} disabled={saving}>
            {saving ? "Сохраняем…" : "Сохранить"}
          </Button>
        </div>
      </Card>

      {versions.length > 0 &&
        (showHistory ? (
          <div className="space-y-2">
            <button
              type="button"
              onClick={() => setShowHistory(false)}
              className="text-sm font-medium text-accent hover:underline"
            >
              Скрыть историю
            </button>
            <Table>
              <table>
                <thead>
                  <tr>
                    <th>Дата</th>
                    <th>Автор</th>
                    <th>Текст</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {versions.map((version) => (
                    <tr key={version.id}>
                      <td className="font-mono">{formatBishkekDateTime(version.created_at)}</td>
                      <td>{version.author}</td>
                      <td>{(version.body ?? "").slice(0, 60)}</td>
                      <td>
                        <Button
                          variant="secondary"
                          onClick={() => void save(version.body ?? "")}
                          disabled={saving}
                        >
                          Откатить
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Table>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setShowHistory(true)}
            className="text-sm font-medium text-accent hover:underline"
          >
            История изменений ({versions.length})
          </button>
        ))}
    </div>
  );
}
