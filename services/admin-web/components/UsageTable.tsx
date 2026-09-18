"use client";

import { useState } from "react";
import { fetchUsage, type UsagePeriod, type UsageSummary } from "@/lib/api";
import { Select } from "@/components/ui/Select";
import { Table } from "@/components/ui/Table";

interface UsageTableProps {
  apiBaseUrl: string;
  summaries: UsageSummary[];
  initialPeriod: UsagePeriod;
}

const PERIOD_LABELS: Record<UsagePeriod, string> = {
  "7d": "7 дней",
  "30d": "30 дней",
  "90d": "90 дней",
  all: "Всё время",
};

function formatCost(cost: string): string {
  // cost — Decimal-строка с бэкенда (см. lib/api.ts) — форматируем как
  // обычное число, точность JS float здесь не критична: экран показывает
  // ОЦЕНКУ, не биллинговые данные (см. подпись под таблицей).
  return Number(cost).toFixed(4);
}

export function UsageTable({ apiBaseUrl, summaries, initialPeriod }: UsageTableProps) {
  const [rows, setRows] = useState(summaries);
  const [period, setPeriod] = useState(initialPeriod);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handlePeriodChange = async (nextPeriod: UsagePeriod) => {
    setPeriod(nextPeriod);
    setError(null);
    setLoading(true);
    try {
      const next = await fetchUsage(apiBaseUrl, nextPeriod);
      setRows(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить расходы");
    } finally {
      setLoading(false);
    }
  };

  const totalTokensIn = rows.reduce((sum, r) => sum + r.tokens_in, 0);
  const totalTokensOut = rows.reduce((sum, r) => sum + r.tokens_out, 0);
  const totalCost = rows.reduce((sum, r) => sum + Number(r.cost), 0);

  return (
    <div className="flex flex-col gap-5">
      <label className="mb-0 block max-w-xs text-sm font-medium text-ink">
        Период
        <Select
          value={period}
          onChange={(e) => void handlePeriodChange(e.target.value as UsagePeriod)}
          aria-label="Период"
          className="mt-1.5"
        >
          {(Object.keys(PERIOD_LABELS) as UsagePeriod[]).map((p) => (
            <option key={p} value={p}>
              {PERIOD_LABELS[p]}
            </option>
          ))}
        </Select>
      </label>

      {loading && <p className="text-sm text-ink-soft">Загружаем…</p>}
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}

      <Table>
        <table>
          <thead>
            <tr>
              <th>Бот</th>
              <th>Токены (вход)</th>
              <th>Токены (выход)</th>
              <th>Стоимость ($)</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.bot_id}>
                <td>{row.bot_name}</td>
                <td className="font-mono">{row.tokens_in.toLocaleString("ru-RU")}</td>
                <td className="font-mono">{row.tokens_out.toLocaleString("ru-RU")}</td>
                <td className="font-mono">{formatCost(row.cost)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td className="font-semibold">Итого</td>
              <td className="font-mono font-semibold">{totalTokensIn.toLocaleString("ru-RU")}</td>
              <td className="font-mono font-semibold">{totalTokensOut.toLocaleString("ru-RU")}</td>
              <td className="font-mono font-semibold">{totalCost.toFixed(4)}</td>
            </tr>
          </tfoot>
        </table>
      </Table>

      <p className="text-xs text-ink-soft">
        Оценка по объявленным ценам OpenAI, не биллинговые данные.
      </p>
    </div>
  );
}
