import type { ReactNode } from "react";

interface TableProps {
  children: ReactNode;
}

const WRAPPER_CLASSES = [
  // overflow-y-hidden обязателен рядом с overflow-x-auto: без него браузер по
  // спеке CSS домысливает overflow-y как auto (раз overflow-x не visible), и
  // любая сабпиксельная нестыковка высоты строк включает вечно видимый
  // вертикальный скроллбар — реально воспроизведено на components/ui/Tabs.tsx
  // (2026-09-19), тот же класс контейнера, тот же фикс на будущее для ЛЮБОЙ
  // таблицы через этот компонент.
  "overflow-x-auto overflow-y-hidden rounded-2xl border border-border bg-surface shadow-card",
  "[&_table]:w-full [&_table]:border-collapse",
  "[&_th]:border-b [&_th]:border-border [&_th]:bg-surface-alt [&_th]:px-4 [&_th]:py-2.5",
  "[&_th]:text-left [&_th]:text-[11px] [&_th]:font-semibold [&_th]:uppercase",
  "[&_th]:tracking-wide [&_th]:text-ink-soft",
  "[&_td]:border-b [&_td]:border-border [&_td]:px-4 [&_td]:py-3 [&_td]:text-sm [&_td]:align-middle",
  "[&_tbody_tr:last-child_td]:border-b-0",
  "[&_tbody_tr:hover]:bg-surface-alt",
].join(" ");

export function Table({ children }: TableProps) {
  return <div className={WRAPPER_CLASSES}>{children}</div>;
}
