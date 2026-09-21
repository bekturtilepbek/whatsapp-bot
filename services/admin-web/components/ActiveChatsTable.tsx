"use client";

import { useState } from "react";
import { releaseChat, type ActiveChat } from "@/lib/api";
import { useToast } from "@/components/ToastProvider";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Table } from "@/components/ui/Table";

interface ActiveChatsTableProps {
  botId: string;
  apiBaseUrl: string;
  initialChats: ActiveChat[];
}

/** Контакт неизвестен БД (см. db.contacts.find_by_identifier — best-effort,
 * не гарантирован) — показываем "голый" JID без домена, лучше, чем ничего. */
function chatLabel(chat: ActiveChat): string {
  return chat.contact_name ?? chat.contact_phone ?? chat.chat_id.split("@")[0];
}

function formatAutoRelease(seconds: number | null): string {
  if (seconds === null) {
    return "—";
  }
  const minutes = Math.ceil(seconds / 60);
  return `~${minutes} мин`;
}

export function ActiveChatsTable({ botId, apiBaseUrl, initialChats }: ActiveChatsTableProps) {
  const { showError, showSuccess } = useToast();
  const [chats, setChats] = useState(initialChats);
  const [releasingId, setReleasingId] = useState<string | null>(null);

  const handleRelease = async (chatId: string) => {
    setReleasingId(chatId);
    try {
      await releaseChat(apiBaseUrl, botId, chatId);
      setChats((current) => current.filter((c) => c.chat_id !== chatId));
      showSuccess("Чат возвращён боту");
    } catch (err) {
      showError(err instanceof Error ? err.message : "Не удалось освободить чат");
    } finally {
      setReleasingId(null);
    }
  };

  if (chats.length === 0) {
    return (
      <EmptyState
        title="Нет активных чатов с участием человека"
        description="Как только менеджер ответит клиенту вручную, диалог появится здесь — бот молчит на него, пока не истечёт таймер авто-возврата или его не освободят вручную."
      />
    );
  }

  return (
    <Table>
      <table>
        <thead>
          <tr>
            <th>Контакт</th>
            <th>Авто-возврат</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {chats.map((chat) => (
            <tr key={chat.chat_id}>
              <td>{chatLabel(chat)}</td>
              <td className="font-mono">{formatAutoRelease(chat.auto_release_in_seconds)}</td>
              <td>
                <Button
                  variant="danger"
                  disabled={releasingId === chat.chat_id}
                  onClick={() => void handleRelease(chat.chat_id)}
                >
                  Освободить
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Table>
  );
}
