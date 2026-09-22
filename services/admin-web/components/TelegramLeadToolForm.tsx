"use client";

import { useState } from "react";
import { deleteBotTool, saveBotTool, type ToolBinding } from "@/lib/api";
import { useToast } from "@/components/ToastProvider";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Switch } from "@/components/ui/Switch";
import { Textarea } from "@/components/ui/Textarea";
import { useInvalidShake } from "@/lib/useInvalidShake";

const TOOL_NAME = "send_telegram_lead";

// Показывается как placeholder — точная копия дефолта из
// libs/tools/src/tools/telegram_lead.py::_DEFAULT_MESSAGE_TEMPLATE (в HTML,
// как реально уходит в Telegram) — не значение по умолчанию поля формы:
// пустое поле означает "использовать этот текст", а не сам этот текст.
const DEFAULT_TEMPLATE_PREVIEW =
  '<b>Новая заявка</b>\n\n<b>Клиент:</b> {client_name}\n<b>Телефон:</b> <code>{phone}</code>\n<b>Детали:</b> {details}{wa_link}';

interface TelegramLeadToolFormProps {
  botId: string;
  apiBaseUrl: string;
  initialBinding: ToolBinding | null;
}

export function TelegramLeadToolForm({
  botId,
  apiBaseUrl,
  initialBinding,
}: TelegramLeadToolFormProps) {
  const { showError, showSuccess } = useToast();
  const [enabled, setEnabled] = useState(initialBinding !== null);
  const [chatId, setChatId] = useState(String(initialBinding?.config.chat_id ?? ""));
  const [messageTemplate, setMessageTemplate] = useState(
    String(initialBinding?.config.message_template ?? ""),
  );
  const [saving, setSaving] = useState(false);
  const { shake, clear, isInvalid, shakeKey } = useInvalidShake();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (enabled && chatId.trim() === "") {
      showError("Укажите ID группы Telegram или выключите отправку заявок");
      shake(["chatId"]);
      return;
    }
    setSaving(true);
    try {
      if (enabled) {
        await saveBotTool(apiBaseUrl, botId, TOOL_NAME, {
          chat_id: chatId.trim(),
          message_template: messageTemplate,
        });
      } else {
        await deleteBotTool(apiBaseUrl, botId, TOOL_NAME);
      }
      showSuccess("Сохранено");
    } catch (err) {
      showError(err instanceof Error ? err.message : "Не удалось сохранить");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={(e) => void handleSubmit(e)} className="space-y-5">
      <Card className="p-5">
        <h2 className="mb-4 text-[15px] font-semibold text-ink">Заявки в Telegram</h2>
        <label className="mb-4 flex items-center gap-2.5 text-sm font-medium text-ink">
          <Switch checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
          Отправлять заявки клиентов в Telegram-группу
        </label>
        <label
          className={`mb-4 block text-sm font-medium ${isInvalid("chatId") ? "text-danger" : "text-ink"}`}
        >
          <div
            key={isInvalid("chatId") ? `chatId-shake-${shakeKey}` : "chatId"}
            className={isInvalid("chatId") ? "animate-shake" : undefined}
          >
            ID группы Telegram
            <Input
              type="text"
              value={chatId}
              onChange={(e) => {
                setChatId(e.target.value);
                clear("chatId");
              }}
              placeholder="-1001234567890"
              disabled={!enabled}
              invalid={isInvalid("chatId")}
              className="mt-1.5 max-w-xs"
            />
          </div>
        </label>
        <label className="mb-0 block text-sm font-medium text-ink">
          Текст сообщения (необязательно)
          <Textarea
            rows={5}
            value={messageTemplate}
            onChange={(e) => setMessageTemplate(e.target.value)}
            placeholder={DEFAULT_TEMPLATE_PREVIEW}
            disabled={!enabled}
            className="mt-1.5 font-mono text-xs"
          />
          <p className="mt-1.5 text-xs text-ink-soft">
            Пусто — используется текст по умолчанию (показан подсказкой). Доступные плейсхолдеры:{" "}
            <code>{"{client_name}"}</code>, <code>{"{phone}"}</code>, <code>{"{details}"}</code>,{" "}
            <code>{"{wa_link}"}</code> (ссылка на чат в WhatsApp).
          </p>
        </label>
      </Card>

      <Button type="submit" disabled={saving}>
        {saving ? "Сохраняем…" : "Сохранить"}
      </Button>
    </form>
  );
}
