"use client";

export type SortDirection = "asc" | "desc";

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
