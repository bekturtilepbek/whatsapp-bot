"use client";

import { useMemo, useState } from "react";
import { releaseChat, type ActiveChat } from "@/lib/api";
import { useToast } from "@/components/ToastProvider";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { compareNullableNumbers, SortableTh, type SortDirection } from "@/components/ui/SortableTh";
import { Table } from "@/components/ui/Table";

interface ActiveChatsTableProps {
  botId: string;
  apiBaseUrl: string;
  initialChats: ActiveChat[];
}

type SortKey = "contact" | "auto_release";

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
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("contact");
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");

  const visibleChats = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = q === "" ? chats : chats.filter((c) => chatLabel(c).toLowerCase().includes(q));
    const sorted = [...filtered].sort((a, b) => {
      if (sortKey === "auto_release") {
        return compareNullableNumbers(
          a.auto_release_in_seconds,
          b.auto_release_in_seconds,
          sortDirection,
        );
      }
      const cmp = chatLabel(a).localeCompare(chatLabel(b), "ru");
      return sortDirection === "asc" ? cmp : -cmp;
    });
    return sorted;
  }, [chats, query, sortKey, sortDirection]);

  function toggleSort(key: SortKey): void {
    if (key === sortKey) {
      setSortDirection((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDirection("asc");
    }
  }

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
    <div className="space-y-4">
      <Input
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Поиск по контакту…"
        aria-label="Поиск активных чатов"
        className="max-w-sm"
      />
      {visibleChats.length === 0 ? (
        <EmptyState title="Ничего не найдено" description="Попробуйте другой запрос." />
      ) : (
        <Table>
          <table>
            <thead>
              <tr>
                <SortableTh
                  label="Контакт"
                  active={sortKey === "contact"}
                  direction={sortDirection}
                  onClick={() => toggleSort("contact")}
                />
                <SortableTh
                  label="Авто-возврат"
                  active={sortKey === "auto_release"}
                  direction={sortDirection}
                  onClick={() => toggleSort("auto_release")}
                />
                <th />
              </tr>
            </thead>
            <tbody>
              {visibleChats.map((chat) => (
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
      )}
    </div>
  );
}
