import type { ButtonHTMLAttributes } from "react";

export type ButtonVariant = "primary" | "secondary" | "danger";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
}

export const BUTTON_BASE_CLASSES =
  "inline-flex items-center gap-2 rounded-md px-3.5 py-2 text-sm font-medium leading-tight transition-colors disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2";

export const BUTTON_VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary: "bg-accent text-white hover:bg-accent-hover",
  secondary: "bg-surface text-ink border border-border hover:border-ink-faint",
  danger: "bg-surface text-danger border border-danger hover:bg-danger/5",
};

export function Button({ variant = "primary", className = "", ...props }: ButtonProps) {
  return (
    <button
      className={`${BUTTON_BASE_CLASSES} ${BUTTON_VARIANT_CLASSES[variant]} ${className}`}
      {...props}
    />
  );
}
