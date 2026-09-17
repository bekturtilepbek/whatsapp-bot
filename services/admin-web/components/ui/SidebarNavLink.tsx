"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

interface SidebarNavLinkProps {
  href: string;
  children: ReactNode;
  /** Точное совпадение по умолчанию — как у TabLink. "Боты" в сайдбаре
   * передаёт exact={false}, чтобы оставаться подсвеченным на /bots/new
   * и на любой /bots/[id]/* странице, не только на самом /bots. */
  exact?: boolean;
}

export function SidebarNavLink({ href, children, exact = true }: SidebarNavLinkProps) {
  const pathname = usePathname();
  const isActive = exact ? pathname === href : (pathname ?? "").startsWith(href);
  return (
    <Link
      href={href}
      aria-current={isActive ? "page" : undefined}
      className={`flex items-center gap-2.5 rounded-lg border-l-[3px] px-2.5 py-2 text-sm transition-colors ${
        isActive
          ? "border-accent bg-accent-soft font-medium text-accent"
          : "border-transparent text-ink-soft hover:bg-surface-alt hover:text-ink"
      }`}
    >
      {children}
    </Link>
  );
}
