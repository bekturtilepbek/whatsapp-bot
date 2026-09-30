"use client";

import { useEffect, useId, useState } from "react";

interface RangeFieldProps {
  label: string;
  unit: string;
  min: number;
  max: number;
  step: number;
  /** Сохранённое значение (baseline). */
  value: number;
  /** Вызывается, когда пользователь ОТПУСТИЛ ползунок (или отпустил клавишу),
   * и только если значение изменилось — не на каждый шаг перетаскивания,
   * иначе автосохранение слало бы десяток PATCH за одно движение. */
  onCommit: (value: number) => void;
  /** Что значение означает на практике — пересчитывается на лету. */
  hint?: (value: number) => string;
}

/** Ползунок настроек бота — как в старой админке V1 (bot_management.html:
 * значение в заголовке), плюс подсказка со смыслом значения. */
export function RangeField({ label, unit, min, max, step, value, onCommit, hint }: RangeFieldProps) {
  const id = useId();
  const [draft, setDraft] = useState(value);

  // Откат снаружи (сбой сохранения) — показываем подтверждённое значение.
  useEffect(() => setDraft(value), [value]);

  function commit(): void {
    if (draft !== value) onCommit(draft);
  }

  return (
    <div>
      <label htmlFor={id} className="flex items-baseline justify-between text-sm font-medium text-ink">
        <span>{label}</span>
        <span className="font-semibold text-accent tabular-nums">
          {draft} {unit}
        </span>
      </label>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={draft}
        onChange={(e) => setDraft(Number(e.target.value))}
        onPointerUp={commit}
        onKeyUp={commit}
        onBlur={commit}
        className="mt-2 w-full cursor-pointer accent-[var(--color-accent)]"
      />
      <div className="flex justify-between text-[11px] text-ink-faint tabular-nums">
        <span>
          {min} {unit}
        </span>
        <span>
          {max} {unit}
        </span>
      </div>
      {hint && <p className="mt-1.5 text-xs text-ink-soft">{hint(draft)}</p>}
    </div>
  );
}
