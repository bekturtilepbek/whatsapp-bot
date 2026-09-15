"use client";

import { useState, type FormEvent } from "react";
import {
  addBlockedNumber,
  deleteBlockedNumber,
  fetchBlockedNumbers,
  type BlockedNumber,
} from "@/lib/api";
import { useToast } from "@/components/ToastProvider";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Table } from "@/components/ui/Table";

interface BlockedNumbersTableProps {
  botId: string;
  apiBaseUrl: string;
  numbers: BlockedNumber[];
  /** Сколько номеров пришло первой (SSR) страницей — совпадает с limit,
   * которым страница делала fetchBlockedNumbers. Тот же приём, что в
   * ProductsTable: пришло МЕНЬШЕ pageSize — дальше грузить нечего. */
  pageSize: number;
}

export function BlockedNumbersTable({
  botId,
  apiBaseUrl,
  numbers,
  pageSize,
}: BlockedNumbersTableProps) {
  const { showError, showSuccess } = useToast();
  const [rows, setRows] = useState(numbers);
  const [phone, setPhone] = useState("");
  const [adding, setAdding] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(numbers.length === pageSize);

  const handleAdd = async (event: FormEvent) => {
    event.preventDefault();
    if (!phone.trim()) {
      return;
    }
    setAdding(true);
    try {
      const added = await addBlockedNumber(apiBaseUrl, botId, phone);
      // POST идемпотентен: если номер уже был в списке — не дублируем строку.
      setRows((current) =>
        current.some((row) => row.phone === added.phone)
          ? current
          : [added, ...current],
      );
      setPhone("");
      showSuccess("Номер добавлен в чёрный список");
    } catch (err) {
      showError(err instanceof Error ? err.message : "Не удалось добавить");
    } finally {
      setAdding(false);
    }
  };

  const handleDelete = async (targetPhone: string) => {
    try {
      await deleteBlockedNumber(apiBaseUrl, botId, targetPhone);
      setRows((current) => current.filter((row) => row.phone !== targetPhone));
      showSuccess("Номер удалён из чёрного списка");
    } catch (err) {
      showError(err instanceof Error ? err.message : "Не удалось удалить");
    }
  };

  const handleLoadMore = async () => {
    // offset от rows.length — тот же принятый риск сдвига страницы при
    // параллельном изменении списка, что и в ProductsTable.
    setLoadingMore(true);
    try {
      const next = await fetchBlockedNumbers(apiBaseUrl, botId, {
        limit: pageSize,
        offset: rows.length,
      });
      setRows((current) => [...current, ...next]);
      setHasMore(next.length === pageSize);
    } catch (err) {
      showError(err instanceof Error ? err.message : "Не удалось загрузить ещё");
    } finally {
      setLoadingMore(false);
    }
  };

  return (
    <div className="space-y-5">
      <Card className="p-5">
        <form onSubmit={(event) => void handleAdd(event)} className="flex items-end gap-3">
          <label className="mb-0 block flex-1 text-sm font-medium text-ink">
            Номер телефона
            <Input
              type="text"
              value={phone}
              onChange={(event) => setPhone(event.target.value)}
              placeholder="+996 700 00 00 00"
              aria-label="Номер телефона"
              className="mt-1.5"
            />
          </label>
          <Button type="submit" disabled={adding}>
            {adding ? "Добавляем…" : "Добавить"}
          </Button>
        </form>
      </Card>

      {rows.length === 0 ? (
        <EmptyState
          title="Чёрный список пуст"
          description="Заблокированные номера не получают ответов от бота."
        />
      ) : (
        <>
          <Table>
            <table>
              <thead>
                <tr>
                  <th>Номер</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.phone}>
                    <td className="font-mono">{row.phone}</td>
                    <td>
                      <Button variant="danger" onClick={() => void handleDelete(row.phone)}>
                        Удалить
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Table>
          {hasMore && (
            <Button
              variant="secondary"
              onClick={() => void handleLoadMore()}
              disabled={loadingMore}
            >
              {loadingMore ? "Загружаем…" : "Показать ещё"}
            </Button>
          )}
        </>
      )}
    </div>
  );
}
