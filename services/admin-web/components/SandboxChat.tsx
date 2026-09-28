"use client";

import { useEffect, useRef, useState } from "react";
import {
  sendSandboxMessage,
  sendSandboxMediaMessage,
  sandboxMediaUrl,
  type SandboxHistoryItem,
  type SandboxMediaItem,
} from "@/lib/api";
import { formatBishkekTime } from "@/lib/formatDate";
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
  // Карточка товара/файл от тулзы (FEATURES.md 9.6 часть A) — эфемерное,
  // отдаётся через ..api/sandbox/media, ничего не хранится в БД для песочницы.
  media?: SandboxMediaItem[];
  // Фото/PDF, которое "клиент" прикрепил в этом ходе (FEATURES.md 9.6 часть
  // B) — превью только локальное (blob URL), на бэкенд файл нигде не
  // сохраняется, поэтому это не SandboxMediaItem.
  attachment?: { name: string; previewUrl?: string };
}

const SUPPORTED_ATTACHMENT_TYPES = "image/*,application/pdf";

function attachmentPlaceholder(file: File): string {
  return file.type.startsWith("image/") ? "[фото]" : "[документ]";
}

const TEXTAREA_MAX_HEIGHT_PX = 120;

// Только время по Бишкеку (не дата) — WhatsApp в пределах одного дня
// показывает именно так. Раньше — toLocaleTimeString() браузера, теперь
// единообразно с остальным кабинетом (lib/formatDate.ts).
function formatTime(): string {
  return formatBishkekTime(new Date().toISOString());
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
  const [attachedFile, setAttachedFile] = useState<File | null>(null);
  const [attachedPreviewUrl, setAttachedPreviewUrl] = useState<string | undefined>(undefined);
  const messagesRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

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

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ""; // сброс — иначе повторный выбор ТОГО ЖЕ файла не даст onChange
    if (!file) return;
    setAttachedFile(file);
    setAttachedPreviewUrl(file.type.startsWith("image/") ? URL.createObjectURL(file) : undefined);
    // Фокус обратно на ввод текста — чтобы можно было сразу дописать подпись
    // и нажать Enter, не кликая по textarea вручную после выбора файла.
    textareaRef.current?.focus();
  };

  const removeAttachment = () => {
    if (attachedPreviewUrl) URL.revokeObjectURL(attachedPreviewUrl);
    setAttachedFile(null);
    setAttachedPreviewUrl(undefined);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const text = input.trim();
    const file = attachedFile;
    if (sending || (!text && !file)) return;

    const history: SandboxHistoryItem[] = messages.map(({ role, content }) => ({ role, content }));
    setMessages((current) => [
      ...current,
      {
        role: "user",
        content: file ? text || attachmentPlaceholder(file) : text,
        time: formatTime(),
        ...(file ? { attachment: { name: file.name, previewUrl: attachedPreviewUrl } } : {}),
      },
    ]);
    setInput("");
    // Превью в уже отправленном пузыре продолжает жить (blob URL не
    // отзывается) — отзыв ломает уже отрисованную картинку. Убираем только
    // рабочее состояние вложения, готовим форму к следующему ходу.
    setAttachedFile(null);
    setAttachedPreviewUrl(undefined);
    requestAnimationFrame(resizeTextarea);
    setSending(true);
    try {
      const result = file
        ? await sendSandboxMediaMessage(apiBaseUrl, botId, history, file, text || undefined)
        : await sendSandboxMessage(apiBaseUrl, botId, history, text);
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
          media: result.media,
        },
      ]);
    } catch (err) {
      showError(err instanceof Error ? err.message : "Не удалось отправить сообщение");
      // Неудачную реплику клиента убираем — иначе следующий запрос уйдёт с
      // "дырой" в истории (сообщение показано, но бот на него не отвечал).
      setMessages((current) => current.slice(0, -1));
    } finally {
      setSending(false);
      // textarea снова disabled=false только ПОСЛЕ этого ре-рендера — focus()
      // на ещё disabled-поле браузер тихо игнорирует, поэтому не сразу, а в
      // следующем кадре (тот же приём, что уже есть у resizeTextarea рядом).
      requestAnimationFrame(() => textareaRef.current?.focus());
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
                {m.attachment &&
                  (m.attachment.previewUrl ? (
                    // eslint-disable-next-line @next/next/no-img-element -- blob URL, next/image тут не нужен
                    <img
                      className="sbx-bubble-media-image"
                      src={m.attachment.previewUrl}
                      alt={m.attachment.name}
                    />
                  ) : (
                    <span className="sbx-bubble-media-file">📎 {m.attachment.name}</span>
                  ))}
                {m.media?.map((item, j) =>
                  item.mime_type.startsWith("image/") ? (
                    // eslint-disable-next-line @next/next/no-img-element -- внешний URL с query-параметрами, next/image тут не нужен
                    <img
                      key={j}
                      className="sbx-bubble-media-image"
                      src={sandboxMediaUrl(apiBaseUrl, botId, item.storage_key, item.mime_type)}
                      alt={m.content}
                    />
                  ) : item.mime_type.startsWith("video/") ? (
                    <video
                      key={j}
                      className="sbx-bubble-media-video"
                      src={sandboxMediaUrl(apiBaseUrl, botId, item.storage_key, item.mime_type)}
                      controls
                    />
                  ) : (
                    <a
                      key={j}
                      className="sbx-bubble-media-file"
                      href={sandboxMediaUrl(apiBaseUrl, botId, item.storage_key, item.mime_type)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      📎 {item.filename ?? item.storage_key}
                    </a>
                  ),
                )}
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

        {attachedFile && (
          <div className="sbx-attachment-preview">
            {attachedPreviewUrl ? (
              // eslint-disable-next-line @next/next/no-img-element -- blob URL, next/image тут не нужен
              <img src={attachedPreviewUrl} alt={attachedFile.name} />
            ) : (
              <span className="sbx-bubble-media-file">📎 {attachedFile.name}</span>
            )}
            <button type="button" aria-label="Убрать вложение" onClick={removeAttachment}>
              ×
            </button>
          </div>
        )}

        <form className="sbx-input-bar" onSubmit={(e) => void handleSubmit(e)}>
          <label className="sbx-attach-button">
            <input
              ref={fileInputRef}
              type="file"
              accept={SUPPORTED_ATTACHMENT_TYPES}
              onChange={handleFileChange}
              disabled={sending}
              aria-label="Прикрепить файл"
              hidden
            />
            <svg
              viewBox="0 0 24 24"
              width="20"
              height="20"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57a4 4 0 1 1 5.66 5.66l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48" />
            </svg>
          </label>
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
            autoFocus
          />
          <button
            type="submit"
            aria-label="Отправить"
            disabled={sending || (!input.trim() && !attachedFile)}
          >
            <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" aria-hidden="true">
              <path d="M2.5 12L21.5 3.5L15 21.5L11 13L2.5 12Z" strokeLinejoin="round" />
            </svg>
          </button>
        </form>
      </div>

      <p className="sbx-note">
        Тулзы бота (товары/файлы) работают по-настоящему; заявки в Telegram и другие тулзы с
        реальным эффектом — глушатся тестовым ответом, реально никуда не уходят. Можно прикрепить
        фото или PDF — ответит vision/PDF-промптом бота, как реальному клиенту. Тратит реальные
        токены OpenAI, видно в «Расходы». История не сохраняется — обновление страницы начинает
        тест заново.
      </p>

      <style>{`
        .sbx-note {
          color: #667781;
          font-size: 0.85em;
          max-width: 420px;
          margin: 1rem auto 0;
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
          /* Мокап всегда выглядит как светлый WhatsApp, независимо от темы
             кабинета (FEATURES.md 9.6 — сознательно, "телефонная" панель).
             Текст пузырей и textarea своего color не задавали — наследовали
             text-ink от <body>, в тёмной теме это светлый цвет поверх
             светлых/белых пузырей и поля ввода = невидимый текст. color
             здесь — не декоративный штрих, а обязательный сброс каскада. */
          color: #111b21;
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

        .sbx-bubble-media-image {
          display: block;
          max-width: 100%;
          border-radius: 6px;
          margin-bottom: 0.3rem;
        }

        .sbx-bubble-media-video {
          display: block;
          max-width: 100%;
          border-radius: 6px;
          margin-bottom: 0.3rem;
        }

        .sbx-bubble-media-file {
          display: block;
          color: inherit;
          text-decoration: underline;
          margin-bottom: 0.3rem;
          word-break: break-all;
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

        .sbx-attachment-preview {
          display: flex;
          align-items: center;
          gap: 0.5rem;
          padding: 0.4rem 0.75rem;
          background: #f0f0f0;
          border-top: 1px solid #ddd;
          flex-shrink: 0;
        }

        .sbx-attachment-preview img {
          height: 40px;
          width: 40px;
          object-fit: cover;
          border-radius: 6px;
        }

        .sbx-attachment-preview button {
          margin-left: auto;
          border: none;
          background: none;
          font-size: 1.1em;
          line-height: 1;
          color: #667781;
          cursor: pointer;
          padding: 0.2rem 0.4rem;
        }

        .sbx-input-bar {
          display: flex;
          align-items: flex-end;
          gap: 0.5rem;
          padding: 0.5rem;
          background: #f0f0f0;
          flex-shrink: 0;
        }

        .sbx-attach-button {
          flex-shrink: 0;
          width: 36px;
          height: 36px;
          display: flex;
          align-items: center;
          justify-content: center;
          border-radius: 50%;
          cursor: pointer;
          color: #54656f;
        }

        .sbx-attach-button:hover {
          background: rgba(0, 0, 0, 0.05);
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
