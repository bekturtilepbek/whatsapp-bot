"use client";

import { useMemo, useState, type FormEvent } from "react";
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
import { SortableTh, type SortDirection } from "@/components/ui/SortableTh";
import { Table } from "@/components/ui/Table";
import { useInvalidShake } from "@/lib/useInvalidShake";

const MIN_PHONE_DIGITS = 7;
const MAX_PHONE_DIGITS = 15;

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
  const [query, setQuery] = useState("");
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");
  const { shake, clear, isInvalid, shakeKey } = useInvalidShake();

  // Единственная колонка — сортировка только по номеру, но клик по
  // заголовку остаётся тем же паттерном, что и в остальных таблицах.
  const visibleRows = useMemo(() => {
    const q = query.trim();
    const filtered = q === "" ? rows : rows.filter((row) => row.phone.includes(q));
    const sorted = [...filtered].sort((a, b) => a.phone.localeCompare(b.phone));
    return sortDirection === "asc" ? sorted : sorted.reverse();
  }, [rows, query, sortDirection]);

  const handleAdd = async (event: FormEvent) => {
    event.preventDefault();
    if (!phone.trim()) {
      showError("Введите номер телефона");
      shake(["phone"]);
      return;
    }
    // Та же проверка, что в API (bots.py, BLOCKED_PHONE_*_DIGITS): без неё
    // "abc" превращался на сервере в "" — неудаляемую пустую строку списка.
    const digits = phone.replace(/\D/g, "").length;
    if (digits < MIN_PHONE_DIGITS || digits > MAX_PHONE_DIGITS) {
      showError(`Номер должен содержать от ${MIN_PHONE_DIGITS} до ${MAX_PHONE_DIGITS} цифр вместе с кодом страны`);
      shake(["phone"]);
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
          <label
            className={`mb-0 block flex-1 text-sm font-medium ${isInvalid("phone") ? "text-danger" : "text-ink"}`}
          >
            <div
              key={isInvalid("phone") ? `phone-shake-${shakeKey}` : "phone"}
              className={isInvalid("phone") ? "animate-shake" : undefined}
            >
              Номер телефона
              <Input
                type="text"
                value={phone}
                onChange={(event) => {
                  setPhone(event.target.value);
                  clear("phone");
                }}
                placeholder="0700 12 34 56 или +996 700 12 34 56"
                invalid={isInvalid("phone")}
                className="mt-1.5"
              />
            </div>
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
          <Input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Поиск по номеру…"
            aria-label="Поиск по чёрному списку"
            className="max-w-sm"
          />
          {visibleRows.length === 0 ? (
            <EmptyState title="Ничего не найдено" description="Попробуйте другой запрос." />
          ) : (
            <Table>
              <table>
                <thead>
                  <tr>
                    <SortableTh
                      label="Номер"
                      active
                      direction={sortDirection}
                      onClick={() => setSortDirection((d) => (d === "asc" ? "desc" : "asc"))}
                    />
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {visibleRows.map((row) => (
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
          )}
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
