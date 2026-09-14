import type { ReactNode } from "react";

interface TabsProps {
  children: ReactNode;
  ariaLabel?: string;
}

export function Tabs({ children, ariaLabel }: TabsProps) {
  return (
    <nav aria-label={ariaLabel} className="mb-6 flex gap-6 border-b border-border">
      {children}
    </nav>
  );
}
