"use client";

import { useState } from "react";
import { AVAILABLE_MODELS, patchBotSettings, type BotSettings, type ProductDisplay } from "@/lib/api";
import { useToast } from "@/components/ToastProvider";
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

type NumericKey = "batch_timeout_seconds" | "auto_release_minutes" | "reminder_delay_minutes";
type TextKey = "reminder_message" | "media_fallback_text" | "media_reaction_emoji";
type NumberDraftKey = NumericKey | "media_max_size_mb";

// Совпадает с MIN_SETTINGS_MINUTES в worker (consumer.py) — там тот же порог
// как второй рубеж, потому что API сам settings не валидирует.
const MIN_MINUTES = 1;

function formatMb(bytes: number): string {
  return String(Number((bytes / BYTES_PER_MB).toFixed(2)));
}

/** Пустое поле — не 0 (Number("") === 0 молча сохранял ноль), а невалидное значение. */
function parseNumber(raw: string): number {
  return raw.trim() === "" ? Number.NaN : Number(raw);
}

const HOURS = Array.from({ length: 24 }, (_, h) => h);

function formatHour(hour: number): string {
  return `${String(hour).padStart(2, "0")}:00`;
}

/** Правила — как в libs/core/src/core/schedule.py (эталон V1). */
function scheduleHint(start: number, end: number): string {
  if (start === end) return "Начало и конец совпадают — бот отвечает круглосуточно.";
  if (start > end) {
    return `Ночная смена: бот отвечает с ${formatHour(start)} через полночь до ${formatHour(end)}.`;
  }
  return `Бот отвечает с ${formatHour(start)} до ${formatHour(end)}.`;
}

function minutesValidator(label: string) {
  return (v: number) =>
    !Number.isFinite(v) || v < MIN_MINUTES ? `${label} — не меньше ${MIN_MINUTES} минуты` : null;
}

interface BotSettingsFormProps {
  botId: string;
  apiBaseUrl: string;
  initialSettings: Required<BotSettings>;
}

/** Настройки бота (2026-09-28 переделка: убрана единая кнопка "Сохранить"
 * внизу формы — по прямому запросу пользователя, не понравилось, что
 * общая кнопка вне зоны видимости после прокрутки. Каждое поле сохраняется
 * сразу — переключатели по onChange (как тумблер "бот активен" на
 * Обзоре, components/QrPanel.tsx), текстовые/числовые поля по blur
 * (не на каждое нажатие клавиши — иначе запрос на каждый символ). На
 * сбое поле откатывается к последнему подтверждённому значению (baseline).
 * Итоговый вид этой вкладки пользователь попросил считать промежуточным —
 * вернёмся обсудить (ползунки вместо number-input и т.п.) отдельно. */
export function BotSettingsForm({ botId, apiBaseUrl, initialSettings }: BotSettingsFormProps) {
  const { showError, showSuccess } = useToast();
  const [baseline, setBaseline] = useState<Required<BotSettings>>(initialSettings);
  const [settings, setSettings] = useState<Required<BotSettings>>(initialSettings);
  // Числовые поля во время набора держат сырую строку: иначе пустое поле
  // мгновенно становится 0, а МБ перерисовываются из байтов с хвостом
  // (16.1 -> 16.1000003814...). В settings число попадает только на blur.
  const [numberDrafts, setNumberDrafts] = useState<Partial<Record<NumberDraftKey, string>>>({});

  function numberFieldProps(key: NumberDraftKey, shown: string, onCommit: () => void) {
    return {
      value: numberDrafts[key] ?? shown,
      onChange: (e: { target: { value: string } }) =>
        setNumberDrafts((prev) => ({ ...prev, [key]: e.target.value })),
      onBlur: onCommit,
    };
  }

  /** Забирает черновик поля (и очищает его); undefined — поле не трогали. */
  function takeDraft(key: NumberDraftKey): string | undefined {
    const raw = numberDrafts[key];
    if (raw !== undefined) {
      setNumberDrafts((prev) => {
        const next = { ...prev };
        delete next[key];
        return next;
      });
    }
    return raw;
  }

  /** Переключатели/select — сохраняются немедленно на change, без blur. */
  async function saveNow(patch: BotSettings): Promise<void> {
    try {
      await patchBotSettings(apiBaseUrl, botId, patch);
      setBaseline((prev) => ({ ...prev, ...patch }));
      showSuccess("Сохранено");
    } catch (err) {
      showError(err instanceof Error ? err.message : "Не удалось сохранить");
      // Ключи patch могли быть только что применены к settings вызывающим
      // кодом (setSettings уже отработал) — откатываем именно их к baseline.
      setSettings((prev) => ({ ...prev, ...(Object.fromEntries(
        Object.keys(patch).map((key) => [key, baseline[key as keyof BotSettings]]),
      ) as BotSettings) }));
    }
  }

  function setAndSaveNow(patch: BotSettings): void {
    setSettings((prev) => ({ ...prev, ...patch }));
    void saveNow(patch);
  }

  /** Числовое поле — валидация + сохранение по blur, только если значение
   * реально изменилось с последнего подтверждённого. */
  async function commitNumber(key: NumericKey, validate: (value: number) => string | null): Promise<void> {
    const raw = takeDraft(key);
    if (raw === undefined) return;
    const value = parseNumber(raw);
    if (value === baseline[key]) return;
    const error = validate(value);
    if (error) {
      showError(error);
      return;
    }
    setSettings((prev) => ({ ...prev, [key]: value }));
    await saveNow({ [key]: value });
  }

  /** Текстовое поле — то же самое, для строковых ключей. */
  async function commitText(key: TextKey, validate?: (value: string) => string | null): Promise<void> {
    const value = settings[key];
    if (value === baseline[key]) return;
    const error = validate?.(value.trim());
    if (error) {
      showError(error);
      setSettings((prev) => ({ ...prev, [key]: baseline[key] }));
      return;
    }
    await saveNow({ [key]: value });
  }

  /** Макс. размер медиа хранится в байтах, редактируется в МБ — отдельная
   * функция, а не commitNumber: нужна конвертация туда-обратно и сравнение
   * с baseline тоже в байтах. */
  async function commitMediaMaxSize(): Promise<void> {
    const raw = takeDraft("media_max_size_mb");
    if (raw === undefined) return;
    const bytes = Math.round(parseNumber(raw) * BYTES_PER_MB);
    if (bytes === baseline.media_max_size_bytes) return;
    if (!Number.isFinite(bytes) || bytes <= 0 || bytes > MAX_MEDIA_MAX_SIZE_BYTES) {
      showError(`Макс. размер медиа должен быть больше 0 и не больше ${MAX_MEDIA_MAX_SIZE_BYTES / BYTES_PER_MB} МБ`);
      return;
    }
    setSettings((prev) => ({ ...prev, media_max_size_bytes: bytes }));
    await saveNow({ media_max_size_bytes: bytes });
  }

  function setProductDisplay(patch: ProductDisplay): void {
    const next = { ...settings.product_display, ...patch };
    setAndSaveNow({ product_display: next });
  }

  return (
    <div className="space-y-5">
      {/* Карточки ниже с одним полем — без видимой <label>-подписи под
          заголовком: заголовок карточки уже называет единственное поле,
          вторая подпись была бы дублирующей (см. "Напоминания"/"Медиа" ниже —
          там подписи нужны, полей несколько). aria-label сохраняет
          доступность для скринридеров. */}
      <Card className="p-5">
        <h2 className="mb-4 text-[15px] font-semibold text-ink">Модель</h2>
        <Select
          value={settings.model}
          onChange={(e) => setAndSaveNow({ model: e.target.value })}
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
        <h2 className="mb-4 text-[15px] font-semibold text-ink">График работы</h2>
        <label className="mb-4 flex items-center gap-2.5 text-sm font-medium text-ink">
          <Switch
            checked={settings.schedule_enabled}
            onChange={(e) => setAndSaveNow({ schedule_enabled: e.target.checked })}
          />
          Работать по графику
        </label>
        <div className="flex flex-wrap items-end gap-4">
          <label className="mb-0 block text-sm font-medium text-ink">
            Начало работы
            <Select
              value={settings.work_start_hour}
              onChange={(e) => setAndSaveNow({ work_start_hour: Number(e.target.value) })}
              disabled={!settings.schedule_enabled}
              className="mt-1.5 w-28"
            >
              {HOURS.map((h) => (
                <option key={h} value={h}>
                  {formatHour(h)}
                </option>
              ))}
            </Select>
          </label>
          <label className="mb-0 block text-sm font-medium text-ink">
            Конец работы
            <Select
              value={settings.work_end_hour}
              onChange={(e) => setAndSaveNow({ work_end_hour: Number(e.target.value) })}
              disabled={!settings.schedule_enabled}
              className="mt-1.5 w-28"
            >
              {HOURS.map((h) => (
                <option key={h} value={h}>
                  {formatHour(h)}
                </option>
              ))}
            </Select>
          </label>
        </div>
        <p className="mt-3 text-xs text-ink-soft">
          {settings.schedule_enabled
            ? scheduleHint(settings.work_start_hour, settings.work_end_hour)
            : "Бот отвечает круглосуточно."}{" "}
          Вне графика бот не отвечает, но сообщения клиентов сохраняются; напоминания
          вне графика не отправляются.
        </p>
      </Card>

      <Card className="p-5">
        <h2 className="mb-4 text-[15px] font-semibold text-ink">Батчинг</h2>
        <NumberField
          min={0}
          step={0.1}
          {...numberFieldProps("batch_timeout_seconds", String(settings.batch_timeout_seconds), () =>
            void commitNumber("batch_timeout_seconds", (v) =>
              !Number.isFinite(v) || v < 0 ? "Таймаут батчинга должен быть числом не меньше 0" : null,
            ),
          )}
          aria-label="Таймаут батчинга, сек"
          className="max-w-xs"
        />
      </Card>

      <Card className="p-5">
        <h2 className="mb-4 text-[15px] font-semibold text-ink">Хэндофф</h2>
        <NumberField
          min={MIN_MINUTES}
          step={1}
          {...numberFieldProps("auto_release_minutes", String(settings.auto_release_minutes), () =>
            void commitNumber("auto_release_minutes", minutesValidator("Авто-возврат")),
          )}
          aria-label="Авто-возврат после ответа менеджера, мин"
          className="max-w-xs"
        />
      </Card>

      <Card className="p-5">
        <h2 className="mb-4 text-[15px] font-semibold text-ink">Напоминания</h2>
        <label className="mb-4 flex items-center gap-2.5 text-sm font-medium text-ink">
          <Switch
            checked={settings.reminder_enabled}
            onChange={(e) => setAndSaveNow({ reminder_enabled: e.target.checked })}
          />
          Включены
        </label>
        <label className="mb-4 block text-sm font-medium text-ink">
          Задержка, мин
          <NumberField
            min={MIN_MINUTES}
            step={1}
            {...numberFieldProps("reminder_delay_minutes", String(settings.reminder_delay_minutes), () =>
              void commitNumber("reminder_delay_minutes", minutesValidator("Задержка напоминания")),
            )}
            className="mt-1.5 max-w-xs"
          />
        </label>
        <label className="mb-0 block text-sm font-medium text-ink">
          Текст напоминания
          <Textarea
            rows={3}
            value={settings.reminder_message}
            onChange={(e) =>
              setSettings((prev) => ({ ...prev, reminder_message: e.target.value }))
            }
            onBlur={() => void commitText("reminder_message")}
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
            onChange={(e) =>
              setSettings((prev) => ({ ...prev, media_fallback_text: e.target.value }))
            }
            onBlur={() =>
              void commitText("media_fallback_text", (v) =>
                v === "" ? "Заглушка на неподдерживаемое медиа не может быть пустой" : null,
              )
            }
            className="mt-1.5"
          />
        </label>
        <label className="mb-4 block text-sm font-medium text-ink">
          Макс. размер входящего медиа, МБ
          <NumberField
            min={0}
            max={MAX_MEDIA_MAX_SIZE_BYTES / BYTES_PER_MB}
            step={0.1}
            {...numberFieldProps("media_max_size_mb", formatMb(settings.media_max_size_bytes), () =>
              void commitMediaMaxSize(),
            )}
            className="mt-1.5 max-w-xs"
          />
        </label>
        <label className="mb-4 flex items-center gap-2.5 text-sm font-medium text-ink">
          <Switch
            checked={settings.media_reaction_enabled}
            onChange={(e) => setAndSaveNow({ media_reaction_enabled: e.target.checked })}
          />
          Реагировать эмодзи на входящее фото/файл/видео
        </label>
        <label className="mb-0 block text-sm font-medium text-ink">
          Эмодзи реакции
          <Input
            type="text"
            value={settings.media_reaction_emoji}
            onChange={(e) =>
              setSettings((prev) => ({ ...prev, media_reaction_emoji: e.target.value }))
            }
            onBlur={() =>
              void commitText("media_reaction_emoji", (v) =>
                v === "" ? "Эмодзи реакции на медиа не может быть пустым" : null,
              )
            }
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
              onChange={(e) => setProductDisplay({ show_name: e.target.checked })}
            />
            Показывать название
          </label>
          <label className="mb-0 flex items-center gap-2.5 text-sm font-medium text-ink">
            <Switch
              checked={settings.product_display.show_description}
              onChange={(e) => setProductDisplay({ show_description: e.target.checked })}
            />
            Показывать описание
          </label>
          <label className="mb-0 flex items-center gap-2.5 text-sm font-medium text-ink">
            <Switch
              checked={settings.product_display.show_price}
              onChange={(e) => setProductDisplay({ show_price: e.target.checked })}
            />
            Показывать цену
          </label>
        </div>
      </Card>
    </div>
  );
}
