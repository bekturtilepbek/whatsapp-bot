"use client";

import { useState, type FormEvent } from "react";
import {
  addBlockedNumber,
  deleteBlockedNumber,
  fetchBlockedNumbers,
  type BlockedNumber,
} from "@/lib/api";
import { useToast } from "@/components/ToastProvider";

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
    <>
      <form onSubmit={(event) => void handleAdd(event)}>
        <input
          type="text"
          value={phone}
          onChange={(event) => setPhone(event.target.value)}
          placeholder="+996 700 00 00 00"
          aria-label="Номер телефона"
        />
        <button type="submit" disabled={adding}>
          {adding ? "Добавляем…" : "Добавить"}
        </button>
      </form>
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
              <td>{row.phone}</td>
              <td>
                <button onClick={() => void handleDelete(row.phone)}>Удалить</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {hasMore && (
        <button onClick={() => void handleLoadMore()} disabled={loadingMore}>
          {loadingMore ? "Загружаем…" : "Показать ещё"}
        </button>
      )}
    </>
  );
}
