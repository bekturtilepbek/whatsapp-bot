import type { HTMLAttributes } from "react";

type CardProps = HTMLAttributes<HTMLDivElement>;

export function Card({ className = "", ...props }: CardProps) {
  return <div className={`rounded-lg border border-border bg-surface ${className}`} {...props} />;
}
