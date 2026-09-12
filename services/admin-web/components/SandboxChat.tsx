"use client";

import { useEffect, useRef, useState } from "react";
import { sendSandboxMessage, type SandboxHistoryItem } from "@/lib/api";
import { useToast } from "@/components/ToastProvider";

interface SandboxChatProps {
  apiBaseUrl: string;
  botId: string;
  botName: string;
}

interface DisplayMessage extends SandboxHistoryItem {
  time: string;
  // Только у ответов бота — своя строка под пузырём (FEATURES.md 9.6:
  // тестовые сообщения тратят реальные токены, полезно видеть сразу).
  usage?: { tokensIn: number; tokensOut: number; model: string };
}

const TEXTAREA_MAX_HEIGHT_PX = 120;

// Только время (не new Date().toLocaleDateString() с датой) — WhatsApp
// в пределах одного дня показывает именно так. Формируется на клиенте в
// момент отправки/получения (не при SSR исходных данных), поэтому в
// отличие от AuditLogTable.tsx здесь нет риска hydration-mismatch.
function formatTime(): string {
  return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

// Обычный <style> (не <style jsx>) — styled-jsx требует SWC/Babel-трансформ
// Next.js, которого нет в тестовом пайплайне (vitest/@vitejs/plugin-react):
// в тестах jsx попадал бы в DOM как обычный атрибут (React-warning), а сам
// CSS не применялся бы. Скоуп — префиксом sbx- на именах классов, без
// автоматической изоляции styled-jsx.
export function SandboxChat({ apiBaseUrl, botId, botName }: SandboxChatProps) {
  const { showError } = useToast();
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const messagesRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = messagesRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, sending]);

  const resizeTextarea = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, TEXTAREA_MAX_HEIGHT_PX)}px`;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const text = input.trim();
    if (!text || sending) return;

    const history: SandboxHistoryItem[] = messages.map(({ role, content }) => ({ role, content }));
    setMessages((current) => [...current, { role: "user", content: text, time: formatTime() }]);
    setInput("");
    requestAnimationFrame(resizeTextarea);
    setSending(true);
    try {
      const result = await sendSandboxMessage(apiBaseUrl, botId, history, text);
      setMessages((current) => [
        ...current,
        {
          role: "assistant",
          content: result.reply,
          time: formatTime(),
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

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleSubmit(e);
    }
  };

  return (
    <div>
      <p className="sbx-note">
        Без вызова тулз (товары/файлы/Telegram-лид) — только текстовый диалог. Тратит реальные
        токены OpenAI, видно в «Расходы». История не сохраняется — обновление страницы начинает
        тест заново.
      </p>

      <div className="sbx-phone">
        <div className="sbx-header">
          <div className="sbx-avatar" aria-hidden="true">
            {botName.trim().charAt(0).toUpperCase() || "?"}
          </div>
          <div>
            <div className="sbx-bot-name">{botName}</div>
            <div className="sbx-bot-sub">{sending ? "печатает…" : "тестовый диалог"}</div>
          </div>
        </div>

        <div className="sbx-messages" ref={messagesRef}>
          {messages.length === 0 && (
            <p className="sbx-empty">Отправьте сообщение, чтобы проверить, как отвечает бот</p>
          )}
          {messages.map((m, i) => (
            <div className={`sbx-row sbx-${m.role}`} key={i}>
              <div className={`sbx-bubble sbx-${m.role}`}>
                <span className="sbx-bubble-text">{m.content}</span>
                <span className="sbx-bubble-time">{m.time}</span>
              </div>
              {m.usage && (
                <div className="sbx-usage-caption">
                  {m.usage.model} · {m.usage.tokensIn}+{m.usage.tokensOut} токенов
                </div>
              )}
            </div>
          ))}
          {sending && (
            <div className="sbx-row sbx-assistant">
              <div className="sbx-bubble sbx-assistant sbx-typing-bubble" aria-label="Бот печатает">
                <span className="sbx-dot" />
                <span className="sbx-dot" />
                <span className="sbx-dot" />
              </div>
            </div>
          )}
        </div>

        <form className="sbx-input-bar" onSubmit={(e) => void handleSubmit(e)}>
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => {
              setInput(e.target.value);
              resizeTextarea();
            }}
            onKeyDown={handleKeyDown}
            placeholder="Сообщение клиента"
            aria-label="Сообщение клиента"
            disabled={sending}
            rows={1}
          />
          <button type="submit" aria-label="Отправить" disabled={sending || !input.trim()}>
            <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" aria-hidden="true">
              <path d="M2.5 12L21.5 3.5L15 21.5L11 13L2.5 12Z" strokeLinejoin="round" />
            </svg>
          </button>
        </form>
      </div>

      <style>{`
        .sbx-note {
          color: #667781;
          font-size: 0.85em;
          max-width: 420px;
          margin: 0 auto 1rem;
        }

        .sbx-phone {
          display: flex;
          flex-direction: column;
          width: 100%;
          max-width: 420px;
          height: 640px;
          margin: 0 auto;
          border-radius: 12px;
          overflow: hidden;
          box-shadow: 0 4px 24px rgba(0, 0, 0, 0.18);
          background: #efeae2;
        }

        .sbx-header {
          display: flex;
          align-items: center;
          gap: 0.75rem;
          padding: 0.75rem 1rem;
          background: #075e54;
          color: #fff;
          flex-shrink: 0;
        }

        .sbx-avatar {
          width: 36px;
          height: 36px;
          border-radius: 50%;
          background: rgba(255, 255, 255, 0.2);
          display: flex;
          align-items: center;
          justify-content: center;
          font-weight: 600;
          flex-shrink: 0;
        }

        .sbx-bot-name {
          font-weight: 600;
          line-height: 1.3;
        }

        .sbx-bot-sub {
          font-size: 0.8em;
          opacity: 0.85;
          line-height: 1.3;
        }

        .sbx-messages {
          flex: 1;
          overflow-y: auto;
          padding: 0.75rem;
          display: flex;
          flex-direction: column;
          gap: 0.35rem;
        }

        .sbx-empty {
          margin: auto;
          text-align: center;
          color: #667781;
          font-size: 0.9em;
          padding: 1rem;
        }

        .sbx-row {
          display: flex;
          flex-direction: column;
          max-width: 80%;
        }

        .sbx-row.sbx-user {
          align-self: flex-end;
          align-items: flex-end;
        }

        .sbx-row.sbx-assistant {
          align-self: flex-start;
          align-items: flex-start;
        }

        .sbx-bubble {
          position: relative;
          padding: 0.45rem 0.6rem;
          border-radius: 7.5px;
          font-size: 0.92em;
          line-height: 1.35;
          box-shadow: 0 1px 0.5px rgba(0, 0, 0, 0.13);
        }

        .sbx-bubble.sbx-user {
          background: #d9fdd3;
          border-top-right-radius: 0;
        }

        .sbx-bubble.sbx-user::before {
          content: "";
          position: absolute;
          top: 0;
          right: -8px;
          width: 0;
          height: 0;
          border-style: solid;
          border-width: 0 0 8px 8px;
          border-color: transparent transparent transparent #d9fdd3;
        }

        .sbx-bubble.sbx-assistant {
          background: #fff;
          border-top-left-radius: 0;
        }

        .sbx-bubble.sbx-assistant::before {
          content: "";
          position: absolute;
          top: 0;
          left: -8px;
          width: 0;
          height: 0;
          border-style: solid;
          border-width: 0 8px 8px 0;
          border-color: transparent #fff transparent transparent;
        }

        .sbx-bubble-text {
          white-space: pre-wrap;
          word-break: break-word;
        }

        .sbx-bubble-time {
          display: block;
          text-align: right;
          font-size: 0.7em;
          color: #667781;
          margin-top: 0.15rem;
        }

        .sbx-usage-caption {
          color: #667781;
          font-size: 0.72em;
          margin-top: 0.15rem;
          padding: 0 0.2rem;
        }

        .sbx-typing-bubble {
          display: flex;
          align-items: center;
          gap: 2px;
          padding: 0.6rem 0.7rem;
        }

        .sbx-dot {
          width: 6px;
          height: 6px;
          border-radius: 50%;
          background: #8696a0;
          animation: sbx-typing-bounce 1.2s infinite;
        }

        .sbx-dot:nth-child(2) {
          animation-delay: 0.15s;
        }

        .sbx-dot:nth-child(3) {
          animation-delay: 0.3s;
        }

        @keyframes sbx-typing-bounce {
          0%,
          60%,
          100% {
            transform: translateY(0);
            opacity: 0.4;
          }
          30% {
            transform: translateY(-4px);
            opacity: 1;
          }
        }

        @media (prefers-reduced-motion: reduce) {
          .sbx-dot {
            animation: none;
            opacity: 0.7;
          }
        }

        .sbx-input-bar {
          display: flex;
          align-items: flex-end;
          gap: 0.5rem;
          padding: 0.5rem;
          background: #f0f0f0;
          flex-shrink: 0;
        }

        .sbx-input-bar textarea {
          flex: 1;
          resize: none;
          max-height: ${TEXTAREA_MAX_HEIGHT_PX}px;
          border: none;
          border-radius: 18px;
          padding: 0.5rem 0.9rem;
          font-family: inherit;
          font-size: 0.92em;
          line-height: 1.3;
          box-sizing: border-box;
        }

        .sbx-input-bar button {
          flex-shrink: 0;
          width: 36px;
          height: 36px;
          padding: 0;
          border: none;
          border-radius: 50%;
          background: #00a884;
          color: #fff;
          display: flex;
          align-items: center;
          justify-content: center;
        }

        .sbx-input-bar button:disabled {
          background: #b6cec7;
          cursor: default;
        }
      `}</style>
    </div>
  );
}
