import type { ReactNode } from "react";

type IconBadgeVariant = "success" | "accent" | "warning" | "danger";
type IconBadgeSize = "md" | "lg";

interface IconBadgeProps {
  variant?: IconBadgeVariant;
  size?: IconBadgeSize;
  children: ReactNode;
}

const VARIANT_CLASSES: Record<IconBadgeVariant, string> = {
  success: "bg-success-soft text-success",
  accent: "bg-accent-soft text-accent",
  warning: "bg-warning-soft text-warning",
  danger: "bg-danger-soft text-danger",
};

const SIZE_CLASSES: Record<IconBadgeSize, string> = {
  md: "h-11 w-11 [&_svg]:h-5 [&_svg]:w-5",
  lg: "h-[60px] w-[60px] [&_svg]:h-7 [&_svg]:w-7",
};

export function IconBadge({ variant = "accent", size = "md", children }: IconBadgeProps) {
  return (
    <span
      className={`inline-flex flex-none items-center justify-center rounded-full ${VARIANT_CLASSES[variant]} ${SIZE_CLASSES[size]}`}
    >
      {children}
    </span>
  );
}
