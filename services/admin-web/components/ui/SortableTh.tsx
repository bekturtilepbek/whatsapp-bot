"use client";

export type SortDirection = "asc" | "desc";

/** Сравнение чисел, где null (нет значения) всегда в конце — в обоих
 * направлениях. Раньше таблицы подставляли ±Infinity: пустые уезжали не в
 * тот конец, а две пустые строки давали Infinity - Infinity = NaN. */
export function compareNullableNumbers(
  a: number | null,
  b: number | null,
  direction: SortDirection,
): number {
  if (a === null || b === null) {
    return a === b ? 0 : a === null ? 1 : -1;
  }
  return direction === "asc" ? a - b : b - a;
}

interface SortableThProps {
  label: string;
  active: boolean;
  direction: SortDirection;
  onClick: () => void;
}

/** Заголовок таблицы с сортировкой по клику — общий вид для всех таблиц
 * кабинета (Table.tsx уже задаёт стиль <th> целиком, здесь только кнопка
 * внутри + индикатор направления). */
export function SortableTh({ label, active, direction, onClick }: SortableThProps) {
  return (
    <th aria-sort={active ? (direction === "asc" ? "ascending" : "descending") : "none"}>
      <button
        type="button"
        onClick={onClick}
        className="inline-flex items-center gap-1 uppercase tracking-wide hover:text-ink"
      >
        {label}
        <span aria-hidden="true" className={active ? "text-ink" : "text-ink-faint"}>
          {active ? (direction === "asc" ? "↑" : "↓") : "↕"}
        </span>
      </button>
    </th>
  );
}
