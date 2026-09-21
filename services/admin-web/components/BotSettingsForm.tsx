"use client";

import { useState } from "react";
import { AVAILABLE_MODELS, patchBotSettings, type BotSettings } from "@/lib/api";
import { useToast } from "@/components/ToastProvider";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { NumberField } from "@/components/ui/NumberField";
import { Select } from "@/components/ui/Select";
import { Switch } from "@/components/ui/Switch";
import { Textarea } from "@/components/ui/Textarea";

const BYTES_PER_MB = 1024 * 1024;
// Не «сколько разрешает WhatsApp» — свой предохранитель поверх лимита
// входящего медиа (FEATURES.md 1.9), причина — OOM прошлой версии (CLAUDE.md).
// Без потолка форма даёт вручную выставить произвольно большой лимит и
// заново открыть тот же риск (найдено code review настроек бота, 2026-09-09).
const MAX_MEDIA_MAX_SIZE_BYTES = 64 * BYTES_PER_MB;

/** Сравнивает текущее состояние формы с последним известным сохранённым —
 * возвращает только реально изменившиеся ключи. Бэкенд уже поддерживает
 * частичный PATCH (шаллоу JSONB-merge, update_bot) — раньше форма всё
 * равно слала весь объект целиком, что навсегда фиксировало в bots.settings
 * дефолтные значения полей, которые администратор не трогал, и на двух
 * параллельных вкладках второе сохранение затирало правки первой (найдено
 * code review настроек бота, 2026-09-09). */
function diffSettings(
  baseline: Required<BotSettings>,
  current: Required<BotSettings>,
): BotSettings {
  const changed: BotSettings = {};
  if (current.batch_timeout_seconds !== baseline.batch_timeout_seconds) {
    changed.batch_timeout_seconds = current.batch_timeout_seconds;
  }
  if (current.auto_release_minutes !== baseline.auto_release_minutes) {
    changed.auto_release_minutes = current.auto_release_minutes;
  }
  if (current.reminder_enabled !== baseline.reminder_enabled) {
    changed.reminder_enabled = current.reminder_enabled;
  }
  if (current.reminder_delay_minutes !== baseline.reminder_delay_minutes) {
    changed.reminder_delay_minutes = current.reminder_delay_minutes;
  }
  if (current.reminder_message !== baseline.reminder_message) {
    changed.reminder_message = current.reminder_message;
  }
  if (current.media_fallback_text !== baseline.media_fallback_text) {
    changed.media_fallback_text = current.media_fallback_text;
  }
  if (current.media_max_size_bytes !== baseline.media_max_size_bytes) {
    changed.media_max_size_bytes = current.media_max_size_bytes;
  }
  if (current.media_reaction_enabled !== baseline.media_reaction_enabled) {
    changed.media_reaction_enabled = current.media_reaction_enabled;
  }
  if (current.media_reaction_emoji !== baseline.media_reaction_emoji) {
    changed.media_reaction_emoji = current.media_reaction_emoji;
  }
  if (current.model !== baseline.model) {
    changed.model = current.model;
  }
  if (
    current.product_display.show_name !== baseline.product_display.show_name ||
    current.product_display.show_description !== baseline.product_display.show_description ||
    current.product_display.show_price !== baseline.product_display.show_price
  ) {
    changed.product_display = current.product_display;
  }
  return changed;
}

/** Возвращает текст ошибки, если форму нельзя сохранять как есть, иначе null.
 * HTML `min`/`max` на input — только подсказка, не защита (не мешает
 * заполнить поле руками мимо спиннера) — реальная проверка здесь. */
function validateSettings(settings: Required<BotSettings>): string | null {
  if (!Number.isFinite(settings.batch_timeout_seconds) || settings.batch_timeout_seconds < 0) {
    return "Таймаут батчинга должен быть числом не меньше 0";
  }
  if (!Number.isFinite(settings.auto_release_minutes) || settings.auto_release_minutes < 0) {
    return "Авто-возврат должен быть числом не меньше 0";
  }
  if (!Number.isFinite(settings.reminder_delay_minutes) || settings.reminder_delay_minutes < 0) {
    return "Задержка напоминания должна быть числом не меньше 0";
  }
  if (
    !Number.isFinite(settings.media_max_size_bytes) ||
    settings.media_max_size_bytes <= 0 ||
    settings.media_max_size_bytes > MAX_MEDIA_MAX_SIZE_BYTES
  ) {
    return `Макс. размер медиа должен быть от 0 до ${MAX_MEDIA_MAX_SIZE_BYTES / BYTES_PER_MB} МБ`;
  }
  if (settings.media_fallback_text.trim() === "") {
    return "Заглушка на неподдерживаемое медиа не может быть пустой";
  }
  if (settings.media_reaction_emoji.trim() === "") {
    return "Эмодзи реакции на медиа не может быть пустым";
  }
  return null;
}

interface BotSettingsFormProps {
  botId: string;
  apiBaseUrl: string;
  initialSettings: Required<BotSettings>;
}

export function BotSettingsForm({ botId, apiBaseUrl, initialSettings }: BotSettingsFormProps) {
  const { showError, showSuccess } = useToast();
  const [baseline, setBaseline] = useState<Required<BotSettings>>(initialSettings);
  const [settings, setSettings] = useState<Required<BotSettings>>(initialSettings);
  const [saving, setSaving] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const validationError = validateSettings(settings);
    if (validationError) {
      showError(validationError);
      return;
    }
    setSaving(true);
    try {
      await patchBotSettings(apiBaseUrl, botId, diffSettings(baseline, settings));
      setBaseline(settings);
      showSuccess("Сохранено");
    } catch (err) {
      showError(err instanceof Error ? err.message : "Не удалось сохранить");
    } finally {
      setSaving(false);
    }
  };

  return (
    // noValidate — иначе браузерная HTML5-валидация (min/max) тихо блокирует
    // submit ДО того, как выполнится validateSettings ниже: часть невалидных
    // значений (за пределами min/max) вообще не дошла бы до нашего сообщения
    // об ошибке, а показала бы (или не показала бы — зависит от браузера)
    // нативный тултип, при этом другие поля без min/max (текстовые) шли бы
    // через кастомную ошибку — несогласованно.
    <form noValidate onSubmit={(e) => void handleSubmit(e)} className="space-y-5">
      {/* Карточки ниже с одним полем — без видимой <label>-подписи под
          заголовком: заголовок карточки уже называет единственное поле,
          вторая подпись была бы дублирующей (см. "Напоминания"/"Медиа" ниже —
          там подписи нужны, полей несколько). aria-label сохраняет
          доступность для скринридеров. */}
      <Card className="p-5">
        <h2 className="mb-4 text-[15px] font-semibold text-ink">Модель</h2>
        <Select
          value={settings.model}
          onChange={(e) => setSettings({ ...settings, model: e.target.value })}
          aria-label="Модель LLM"
          className="max-w-xs"
        >
          {AVAILABLE_MODELS.map((model) => (
            <option key={model} value={model}>
              {model}
            </option>
          ))}
        </Select>
      </Card>

      <Card className="p-5">
        <h2 className="mb-4 text-[15px] font-semibold text-ink">Батчинг</h2>
        <NumberField
          min={0}
          step={0.1}
          value={settings.batch_timeout_seconds}
          onChange={(e) =>
            setSettings({ ...settings, batch_timeout_seconds: Number(e.target.value) })
          }
          aria-label="Таймаут батчинга, сек"
          className="max-w-xs"
        />
      </Card>

      <Card className="p-5">
        <h2 className="mb-4 text-[15px] font-semibold text-ink">Хэндофф</h2>
        <NumberField
          min={0}
          step={1}
          value={settings.auto_release_minutes}
          onChange={(e) =>
            setSettings({ ...settings, auto_release_minutes: Number(e.target.value) })
          }
          aria-label="Авто-возврат после ответа менеджера, мин"
          className="max-w-xs"
        />
      </Card>

      <Card className="p-5">
        <h2 className="mb-4 text-[15px] font-semibold text-ink">Напоминания</h2>
        <label className="mb-4 flex items-center gap-2.5 text-sm font-medium text-ink">
          <Switch
            checked={settings.reminder_enabled}
            onChange={(e) => setSettings({ ...settings, reminder_enabled: e.target.checked })}
          />
          Включены
        </label>
        <label className="mb-4 block text-sm font-medium text-ink">
          Задержка, мин
          <NumberField
            min={0}
            step={1}
            value={settings.reminder_delay_minutes}
            onChange={(e) =>
              setSettings({ ...settings, reminder_delay_minutes: Number(e.target.value) })
            }
            className="mt-1.5 max-w-xs"
          />
        </label>
        <label className="mb-0 block text-sm font-medium text-ink">
          Текст напоминания
          <Textarea
            rows={3}
            value={settings.reminder_message}
            onChange={(e) => setSettings({ ...settings, reminder_message: e.target.value })}
            className="mt-1.5"
          />
        </label>
      </Card>

      <Card className="p-5">
        <h2 className="mb-4 text-[15px] font-semibold text-ink">Медиа</h2>
        <label className="mb-4 block text-sm font-medium text-ink">
          Заглушка на неподдерживаемое медиа
          <Textarea
            rows={3}
            value={settings.media_fallback_text}
            onChange={(e) => setSettings({ ...settings, media_fallback_text: e.target.value })}
            className="mt-1.5"
          />
        </label>
        <label className="mb-4 block text-sm font-medium text-ink">
          Макс. размер входящего медиа, МБ
          <NumberField
            min={0}
            max={MAX_MEDIA_MAX_SIZE_BYTES / BYTES_PER_MB}
            step={0.1}
            value={settings.media_max_size_bytes / BYTES_PER_MB}
            onChange={(e) =>
              setSettings({
                ...settings,
                media_max_size_bytes: Math.round(Number(e.target.value) * BYTES_PER_MB),
              })
            }
            className="mt-1.5 max-w-xs"
          />
        </label>
        <label className="mb-4 flex items-center gap-2.5 text-sm font-medium text-ink">
          <Switch
            checked={settings.media_reaction_enabled}
            onChange={(e) =>
              setSettings({ ...settings, media_reaction_enabled: e.target.checked })
            }
          />
          Реагировать эмодзи на входящее фото/файл/видео
        </label>
        <label className="mb-0 block text-sm font-medium text-ink">
          Эмодзи реакции
          <Input
            type="text"
            value={settings.media_reaction_emoji}
            onChange={(e) => setSettings({ ...settings, media_reaction_emoji: e.target.value })}
            className="mt-1.5 max-w-xs"
          />
        </label>
      </Card>

      <Card className="p-5">
        <h2 className="mb-4 text-[15px] font-semibold text-ink">Вывод товаров</h2>
        <p className="mb-4 text-xs text-ink-soft">
          Применяется ко всем товарам бота, кроме тех, где включено своё переопределение
          (вкладка «Товары» → карточка товара).
        </p>
        <div className="flex flex-col gap-3">
          <label className="mb-0 flex items-center gap-2.5 text-sm font-medium text-ink">
            <Switch
              checked={settings.product_display.show_name}
              onChange={(e) =>
                setSettings({
                  ...settings,
                  product_display: { ...settings.product_display, show_name: e.target.checked },
                })
              }
            />
            Показывать название
          </label>
          <label className="mb-0 flex items-center gap-2.5 text-sm font-medium text-ink">
            <Switch
              checked={settings.product_display.show_description}
              onChange={(e) =>
                setSettings({
                  ...settings,
                  product_display: {
                    ...settings.product_display,
                    show_description: e.target.checked,
                  },
                })
              }
            />
            Показывать описание
          </label>
          <label className="mb-0 flex items-center gap-2.5 text-sm font-medium text-ink">
            <Switch
              checked={settings.product_display.show_price}
              onChange={(e) =>
                setSettings({
                  ...settings,
                  product_display: { ...settings.product_display, show_price: e.target.checked },
                })
              }
            />
            Показывать цену
          </label>
        </div>
      </Card>

      <Button type="submit" disabled={saving}>
        {saving ? "Сохраняем…" : "Сохранить"}
      </Button>
    </form>
  );
}
