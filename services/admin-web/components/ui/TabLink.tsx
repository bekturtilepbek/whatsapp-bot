"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

interface TabLinkProps {
  href: string;
  children: ReactNode;
  /** Точное совпадение по умолчанию — иначе "/bots/1" (вкладка «Обзор»)
   * подсвечивалась бы активной и на "/bots/1/settings". */
  exact?: boolean;
}

export function TabLink({ href, children, exact = true }: TabLinkProps) {
  const pathname = usePathname();
  const isActive = exact ? pathname === href : pathname.startsWith(href);
  return (
    <Link
      href={href}
      aria-current={isActive ? "page" : undefined}
      className={`-mb-px border-b-2 px-1 pb-3 text-sm ${
        isActive ? "border-accent font-medium text-ink" : "border-transparent text-ink-soft hover:text-ink"
      }`}
    >
      {children}
    </Link>
  );
}
