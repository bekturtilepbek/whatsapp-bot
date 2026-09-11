"use client";

import { useState } from "react";
import { fetchPromptVersions, patchBotPrompt, type PromptKind, type PromptVersion } from "@/lib/api";
import { useToast } from "@/components/ToastProvider";

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
    <section>
      <h2>{label}</h2>
      <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={6} />
      <div>
        <button onClick={() => void save(body)} disabled={saving}>
          {saving ? "Сохраняем…" : "Сохранить"}
        </button>
      </div>
      <ul>
        {versions.map((version) => (
          <li key={version.id}>
            {/* Чистая строковая операция над ISO-текстом, не new Date(...) —
             * иначе разное форматирование на SSR и на клиенте даёт
             * hydration-mismatch (урок QR-экрана, components/QrPanel.tsx). */}
            <span>{version.created_at.slice(0, 16).replace("T", " ")}</span>{" "}
            <span>{version.author}</span>{" "}
            <span>{(version.body ?? "").slice(0, 60)}</span>{" "}
            <button onClick={() => void save(version.body ?? "")} disabled={saving}>
              Откатить
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
