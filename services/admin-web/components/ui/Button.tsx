import type { ButtonHTMLAttributes } from "react";

export type ButtonVariant = "primary" | "secondary" | "danger";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
}

const BUTTON_BASE_CLASSES =
  "inline-flex items-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium leading-tight transition-colors active:scale-[.97] disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2";

const BUTTON_VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary: "bg-accent text-white hover:bg-accent-hover",
  secondary: "bg-surface text-ink border border-border hover:border-ink-faint",
  danger: "bg-surface text-danger border border-danger hover:bg-danger hover:text-white",
};

/** Собирает те же классы, что рендерит Button — для случаев, когда элемент
 * должен ВЫГЛЯДЕТЬ как кнопка, но не может быть настоящим <button> (например,
 * next/link для навигации: <button> нельзя вкладывать в <a>, а список ссылок
 * с action-кнопками в шапках экранов — частый паттерн). Пример использования —
 * app/bots/page.tsx ("Создать бота →"). */
export function buttonClasses(variant: ButtonVariant = "primary", className = ""): string {
  return `${BUTTON_BASE_CLASSES} ${BUTTON_VARIANT_CLASSES[variant]} ${className}`;
}

export function Button({ variant = "primary", className = "", ...props }: ButtonProps) {
  return <button className={buttonClasses(variant, className)} {...props} />;
}
