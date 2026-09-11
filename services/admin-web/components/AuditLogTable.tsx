"use client";

import { useState } from "react";
import { fetchAuditLog, type AuditLogEntry, type Bot } from "@/lib/api";

interface AuditLogTableProps {
  apiBaseUrl: string;
  entries: AuditLogEntry[];
  bots: Bot[];
  /** Совпадает с лимитом, которым страница делала первый fetchAuditLog —
   * тот же приём, что в BlockedNumbersTable/ProductsTable: пришло МЕНЬШЕ
   * pageSize — дальше грузить нечего. */
  pageSize: number;
}

function formatTimestamp(iso: string): string {
  // Чистая строковая операция, не new Date() — иначе разное форматирование
  // на SSR и на клиенте даёт hydration-mismatch (тот же урок, что в
  // PromptEditor.tsx).
  return iso.slice(0, 16).replace("T", " ");
}

export function AuditLogTable({ apiBaseUrl, entries, bots, pageSize }: AuditLogTableProps) {
  const [rows, setRows] = useState(entries);
  const [botFilter, setBotFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const [hasMore, setHasMore] = useState(entries.length === pageSize);
  const [error, setError] = useState<string | null>(null);

  const handleFilterChange = async (nextBotId: string) => {
    setBotFilter(nextBotId);
    setError(null);
    setLoading(true);
    try {
      const next = await fetchAuditLog(apiBaseUrl, {
        botId: nextBotId || undefined,
        limit: pageSize,
      });
      setRows(next);
      setHasMore(next.length === pageSize);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить лог");
    } finally {
      setLoading(false);
    }
  };

  const handleLoadMore = async () => {
    setError(null);
    setLoading(true);
    try {
      const next = await fetchAuditLog(apiBaseUrl, {
        botId: botFilter || undefined,
        limit: pageSize,
        offset: rows.length,
      });
      setRows((current) => [...current, ...next]);
      setHasMore(next.length === pageSize);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить ещё");
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <label>
        Бот
        <select
          value={botFilter}
          onChange={(e) => void handleFilterChange(e.target.value)}
          aria-label="Фильтр по боту"
        >
          <option value="">Все боты</option>
          {bots.map((bot) => (
            <option key={bot.id} value={bot.id}>
              {bot.name}
            </option>
          ))}
        </select>
      </label>
      {error && (
        <p role="alert" style={{ color: "crimson" }}>
          {error}
        </p>
      )}
      <table>
        <thead>
          <tr>
            <th>Время</th>
            <th>Кто</th>
            <th>Бот</th>
            <th>Действие</th>
            <th>Payload</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((entry) => (
            <tr key={entry.id}>
              <td>{formatTimestamp(entry.created_at)}</td>
              <td>{entry.actor_email}</td>
              <td>{entry.bot_name ?? "—"}</td>
              <td>
                <code>{entry.action}</code>
              </td>
              <td>
                {entry.payload && (
                  <details>
                    <summary>показать</summary>
                    <pre>{JSON.stringify(entry.payload, null, 2)}</pre>
                  </details>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {hasMore && (
        <button onClick={() => void handleLoadMore()} disabled={loading}>
          {loading ? "Загружаем…" : "Показать ещё"}
        </button>
      )}
    </>
  );
}
