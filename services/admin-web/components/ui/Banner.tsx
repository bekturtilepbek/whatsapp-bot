import type { ReactNode } from "react";

type BannerVariant = "success" | "accent" | "warning" | "danger";

interface BannerProps {
  variant?: BannerVariant;
  icon: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
}

const SURFACE_CLASSES: Record<BannerVariant, string> = {
  success: "bg-success-soft border-success/25",
  accent: "bg-accent-soft border-accent/25",
  warning: "bg-warning-soft border-warning/25",
  danger: "bg-danger-soft border-danger/25",
};

const TITLE_CLASSES: Record<BannerVariant, string> = {
  success: "text-success",
  accent: "text-accent",
  warning: "text-warning",
  danger: "text-danger",
};

export function Banner({ variant = "accent", icon, title, description, action }: BannerProps) {
  return (
    <div
      className={`mb-5 flex flex-wrap items-start justify-between gap-4 rounded-xl border p-4 shadow-elevated ${SURFACE_CLASSES[variant]}`}
    >
      <div className="flex items-start gap-3">
        <span className={`mt-0.5 flex-none ${TITLE_CLASSES[variant]}`}>{icon}</span>
        <div>
          <p className={`text-sm font-bold ${TITLE_CLASSES[variant]}`}>{title}</p>
          {description && <p className="mt-0.5 text-[13px] leading-relaxed text-ink-soft">{description}</p>}
        </div>
      </div>
      {action}
    </div>
  );
}
