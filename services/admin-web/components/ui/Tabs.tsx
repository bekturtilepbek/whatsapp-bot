import type { ReactNode } from "react";

interface TabsProps {
  children: ReactNode;
  ariaLabel?: string;
}

export function Tabs({ children, ariaLabel }: TabsProps) {
  return (
    <nav
      aria-label={ariaLabel}
      // overflow-x-auto + flex-nowrap: если вкладки не помещаются (узкое
      // окно), скроллится САМА полоска вкладок — не вся страница (см.
      // комментарий в app/layout.tsx о найденном при живой проверке баге).
      className="mb-6 flex flex-nowrap gap-6 overflow-x-auto border-b border-border"
    >
      {children}
    </nav>
  );
}
