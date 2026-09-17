import type { HTMLAttributes } from "react";

type CardProps = HTMLAttributes<HTMLDivElement>;

export function Card({ className = "", ...props }: CardProps) {
  return (
    <div className={`rounded-2xl border border-border bg-surface shadow-card ${className}`} {...props} />
  );
}
