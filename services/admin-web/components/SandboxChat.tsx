"use client";

import { useState } from "react";
import { sendSandboxMessage, type SandboxHistoryItem } from "@/lib/api";
import { useToast } from "@/components/ToastProvider";

interface SandboxChatProps {
  apiBaseUrl: string;
  botId: string;
}

interface DisplayMessage extends SandboxHistoryItem {
  // Только у ответов бота — своя строка под пузырём (FEATURES.md 9.6:
  // тестовые сообщения тратят реальные токены, полезно видеть сразу).
  usage?: { tokensIn: number; tokensOut: number; model: string };
}

export function SandboxChat({ apiBaseUrl, botId }: SandboxChatProps) {
  const { showError } = useToast();
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const text = input.trim();
    if (!text || sending) return;

    const history: SandboxHistoryItem[] = messages.map(({ role, content }) => ({ role, content }));
    setMessages((current) => [...current, { role: "user", content: text }]);
    setInput("");
    setSending(true);
    try {
      const result = await sendSandboxMessage(apiBaseUrl, botId, history, text);
      setMessages((current) => [
        ...current,
        {
          role: "assistant",
          content: result.reply,
          usage: {
            tokensIn: result.tokens_in,
            tokensOut: result.tokens_out,
            model: result.model,
          },
        },
      ]);
    } catch (err) {
      showError(err instanceof Error ? err.message : "Не удалось отправить сообщение");
      // Неудачную реплику клиента убираем — иначе следующий запрос уйдёт с
      // "дырой" в истории (сообщение показано, но бот на него не отвечал).
      setMessages((current) => current.slice(0, -1));
    } finally {
      setSending(false);
    }
  };

  return (
    <div>
      <p style={{ color: "gray", fontSize: "0.85em" }}>
        Без вызова тулз (товары/файлы/Telegram-лид) — только текстовый диалог. Тратит реальные
        токены OpenAI, видно в «Расходы». История не сохраняется — обновление страницы начинает
        тест заново.
      </p>
      <ul style={{ listStyle: "none", padding: 0 }}>
        {messages.map((m, i) => (
          <li key={i}>
            <strong>{m.role === "user" ? "Вы" : "Бот"}:</strong> {m.content}
            {m.usage && (
              <div style={{ color: "gray", fontSize: "0.8em" }}>
                {m.usage.model} · {m.usage.tokensIn}+{m.usage.tokensOut} токенов
              </div>
            )}
          </li>
        ))}
      </ul>
      {messages.length === 0 && <p>Отправьте сообщение, чтобы проверить, как отвечает бот</p>}
      <form onSubmit={(e) => void handleSubmit(e)}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Сообщение клиента"
          aria-label="Сообщение клиента"
          disabled={sending}
        />
        <button type="submit" disabled={sending || !input.trim()}>
          {sending ? "Отправка…" : "Отправить"}
        </button>
      </form>
    </div>
  );
}
