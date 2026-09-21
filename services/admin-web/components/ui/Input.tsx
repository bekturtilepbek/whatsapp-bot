import type { InputHTMLAttributes } from "react";

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  /** Красная рамка + красный focus-outline — для required-поля, не
   * прошедшего валидацию (lib/useInvalidShake.ts). Отдельный проп, не часть
   * className: base-класс жёстко завязан на border-border/outline-accent,
   * переопределить цвет через добавленный в конец className нельзя
   * надёжно — конфликтующие Tailwind-утилиты не гарантируют победу
   * последней в строке. */
  invalid?: boolean;
}

export function Input({ className = "", invalid = false, ...props }: InputProps) {
  return (
    <input
      aria-invalid={invalid || undefined}
      className={`w-full rounded-lg border bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 disabled:cursor-not-allowed disabled:opacity-60 ${invalid ? "border-danger focus-visible:outline-danger" : "border-border focus-visible:outline-accent"} ${className}`}
      {...props}
    />
  );
}
