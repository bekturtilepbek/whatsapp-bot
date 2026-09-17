import type { ReactNode } from "react";

interface EmptyStateProps {
  title: string;
  description?: string;
  action?: ReactNode;
}

export function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <div className="rounded-2xl border border-dashed border-border px-6 py-12 text-center">
      <h3 className="text-sm font-semibold text-ink">{title}</h3>
      {description && <p className="mt-1.5 text-sm text-ink-soft">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
