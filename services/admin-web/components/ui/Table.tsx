import type { ReactNode } from "react";

interface TableProps {
  children: ReactNode;
}

const WRAPPER_CLASSES = [
  "overflow-x-auto rounded-2xl border border-border bg-surface shadow-card",
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
