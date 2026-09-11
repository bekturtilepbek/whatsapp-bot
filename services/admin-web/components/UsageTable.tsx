"use client";

import { useState } from "react";
import { fetchUsage, type UsagePeriod, type UsageSummary } from "@/lib/api";

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
    <>
      <label>
        Период
        <select
          value={period}
          onChange={(e) => void handlePeriodChange(e.target.value as UsagePeriod)}
          aria-label="Период"
        >
          {(Object.keys(PERIOD_LABELS) as UsagePeriod[]).map((p) => (
            <option key={p} value={p}>
              {PERIOD_LABELS[p]}
            </option>
          ))}
        </select>
      </label>
      {loading && <p>Загружаем…</p>}
      {error && (
        <p role="alert" style={{ color: "crimson" }}>
          {error}
        </p>
      )}
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
              <td>{row.tokens_in.toLocaleString("ru-RU")}</td>
              <td>{row.tokens_out.toLocaleString("ru-RU")}</td>
              <td>{formatCost(row.cost)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td>Итого</td>
            <td>{totalTokensIn.toLocaleString("ru-RU")}</td>
            <td>{totalTokensOut.toLocaleString("ru-RU")}</td>
            <td>{totalCost.toFixed(4)}</td>
          </tr>
        </tfoot>
      </table>
      <p style={{ color: "gray", fontSize: "0.85em" }}>
        Оценка по объявленным ценам OpenAI, не биллинговые данные.
      </p>
    </>
  );
}
