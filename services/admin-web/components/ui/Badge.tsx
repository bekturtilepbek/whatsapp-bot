import type { HTMLAttributes } from "react";

type BadgeVariant = "owner" | "paused" | "neutral" | "success" | "danger";

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
}

const BADGE_VARIANT_CLASSES: Record<BadgeVariant, string> = {
  owner: "bg-accent-soft text-accent",
  paused: "bg-warning-soft text-warning",
  neutral: "bg-surface-alt text-ink-soft",
  success: "bg-success-soft text-success",
  danger: "bg-danger-soft text-danger",
};

export function Badge({ variant = "neutral", className = "", ...props }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${BADGE_VARIANT_CLASSES[variant]} ${className}`}
      {...props}
    />
  );
}
