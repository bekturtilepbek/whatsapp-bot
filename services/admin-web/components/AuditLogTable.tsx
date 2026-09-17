"use client";

import { useState } from "react";
import { fetchAuditLog, type AuditLogEntry, type Bot } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Select } from "@/components/ui/Select";
import { Table } from "@/components/ui/Table";

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
    <div className="space-y-5">
      <label className="mb-0 block max-w-xs text-sm font-medium text-ink">
        Бот
        <Select
          value={botFilter}
          onChange={(e) => void handleFilterChange(e.target.value)}
          aria-label="Фильтр по боту"
          className="mt-1.5"
        >
          <option value="">Все боты</option>
          {bots.map((bot) => (
            <option key={bot.id} value={bot.id}>
              {bot.name}
            </option>
          ))}
        </Select>
      </label>

      {error && <p role="alert" className="text-sm text-danger">{error}</p>}

      {rows.length === 0 ? (
        <EmptyState
          title={botFilter ? "По этому боту записей нет" : "Записей аудит-лога пока нет"}
        />
      ) : (
        <>
          <Table>
            <table>
              <thead>
                <tr>
                  <th>Время (UTC)</th>
                  <th>Кто</th>
                  <th>Бот</th>
                  <th>Действие</th>
                  <th>Payload</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((entry) => (
                  <tr key={entry.id}>
                    <td className="font-mono">{formatTimestamp(entry.created_at)}</td>
                    <td>{entry.actor_email}</td>
                    <td>{entry.bot_name ?? "—"}</td>
                    <td>
                      <code className="font-mono text-xs">{entry.action}</code>
                    </td>
                    <td>
                      {entry.payload && (
                        <details>
                          <summary className="cursor-pointer text-sm text-accent">показать</summary>
                          <pre className="mt-1.5 max-w-md overflow-x-auto rounded-lg bg-surface-alt p-2 text-xs">
                            {JSON.stringify(entry.payload, null, 2)}
                          </pre>
                        </details>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Table>
          {hasMore && (
            <Button variant="secondary" onClick={() => void handleLoadMore()} disabled={loading}>
              {loading ? "Загружаем…" : "Показать ещё"}
            </Button>
          )}
        </>
      )}
    </div>
  );
}
