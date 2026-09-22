import type { TextareaHTMLAttributes } from "react";

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  /** См. Input.tsx — та же причина отдельного пропа вместо className. */
  invalid?: boolean;
}

export function Textarea({ className = "", invalid = false, ...props }: TextareaProps) {
  return (
    <textarea
      aria-invalid={invalid || undefined}
      className={`block w-full rounded-lg border bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 disabled:cursor-not-allowed disabled:opacity-60 ${invalid ? "border-danger focus-visible:outline-danger" : "border-border focus-visible:outline-accent"} ${className}`}
      {...props}
    />
  );
}
