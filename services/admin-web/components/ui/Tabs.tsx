import type { ReactNode } from "react";

interface TabsProps {
  children: ReactNode;
}

export function Tabs({ children }: TabsProps) {
  return <nav className="mb-6 flex gap-6 border-b border-border">{children}</nav>;
}
