"use client";

import { useState } from "react";
import { patchBotSettings, type BotSettings } from "@/lib/api";

const BYTES_PER_MB = 1024 * 1024;

interface BotSettingsFormProps {
  botId: string;
  apiBaseUrl: string;
  initialSettings: Required<BotSettings>;
}

export function BotSettingsForm({ botId, apiBaseUrl, initialSettings }: BotSettingsFormProps) {
  const [settings, setSettings] = useState<Required<BotSettings>>(initialSettings);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      await patchBotSettings(apiBaseUrl, botId, settings);
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={(e) => void handleSubmit(e)}>
      <section>
        <h2>Батчинг</h2>
        <label>
          Таймаут батчинга, сек
          <input
            type="number"
            min={0}
            step={0.1}
            value={settings.batch_timeout_seconds}
            onChange={(e) =>
              setSettings({ ...settings, batch_timeout_seconds: Number(e.target.value) })
            }
          />
        </label>
      </section>

      <section>
        <h2>Хэндофф</h2>
        <label>
          Авто-возврат после ответа менеджера, мин
          <input
            type="number"
            min={0}
            step={1}
            value={settings.auto_release_minutes}
            onChange={(e) =>
              setSettings({ ...settings, auto_release_minutes: Number(e.target.value) })
            }
          />
        </label>
      </section>

      <section>
        <h2>Напоминания</h2>
        <label>
          <input
            type="checkbox"
            checked={settings.reminder_enabled}
            onChange={(e) => setSettings({ ...settings, reminder_enabled: e.target.checked })}
          />
          Включены
        </label>
        <label>
          Задержка, мин
          <input
            type="number"
            min={0}
            step={1}
            value={settings.reminder_delay_minutes}
            onChange={(e) =>
              setSettings({ ...settings, reminder_delay_minutes: Number(e.target.value) })
            }
          />
        </label>
        <label>
          Текст напоминания
          <textarea
            rows={3}
            value={settings.reminder_message}
            onChange={(e) => setSettings({ ...settings, reminder_message: e.target.value })}
          />
        </label>
      </section>

      <section>
        <h2>Медиа</h2>
        <label>
          Заглушка на неподдерживаемое медиа
          <textarea
            rows={3}
            value={settings.media_fallback_text}
            onChange={(e) => setSettings({ ...settings, media_fallback_text: e.target.value })}
          />
        </label>
        <label>
          Макс. размер входящего медиа, МБ
          <input
            type="number"
            min={0}
            step={0.1}
            value={settings.media_max_size_bytes / BYTES_PER_MB}
            onChange={(e) =>
              setSettings({
                ...settings,
                media_max_size_bytes: Math.round(Number(e.target.value) * BYTES_PER_MB),
              })
            }
          />
        </label>
      </section>

      <button type="submit" disabled={saving}>
        {saving ? "Сохраняем…" : "Сохранить"}
      </button>
      {saved && !error && <p role="status">Сохранено</p>}
      {error && (
        <p role="alert" style={{ color: "crimson" }}>
          {error}
        </p>
      )}
    </form>
  );
}
