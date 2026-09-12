import type { InputHTMLAttributes } from "react";

// Настоящий <input type="checkbox"> под стилизацией «тумблера» — сохраняет
// нативный implicit role="checkbox" (не role="switch"): существующие и
// будущие тесты форм ищут переключатели через getByRole("checkbox"), явный
// role здесь его бы перекрыл (см. Global Constraints плана).
type SwitchProps = Omit<InputHTMLAttributes<HTMLInputElement>, "type">;

export function Switch({ className = "", ...props }: SwitchProps) {
  return (
    <input
      type="checkbox"
      className={`relative h-5 w-9 shrink-0 cursor-pointer appearance-none rounded-full bg-border transition-colors before:absolute before:left-0.5 before:top-0.5 before:h-4 before:w-4 before:rounded-full before:bg-white before:transition-transform checked:bg-accent checked:before:translate-x-4 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-60 ${className}`}
      {...props}
    />
  );
}
