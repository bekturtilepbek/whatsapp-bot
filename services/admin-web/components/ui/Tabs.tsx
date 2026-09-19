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
      // overflow-y-hidden обязателен рядом: без него браузер по спеке CSS
      // сам домысливает overflow-y как auto (раз overflow-x не visible), и
      // сабпиксельная нестыковка высоты между nav и дочерними TabLink (~0.2px)
      // включает вечно видимый вертикальный скроллбар на полоске вкладок.
      className="mb-6 flex flex-nowrap gap-6 overflow-x-auto overflow-y-hidden border-b border-border"
    >
      {children}
    </nav>
  );
}
