import type { ComponentProps } from "react";
import { Input } from "@/components/ui/Input";

// ComponentProps<typeof Input>, а не InputHTMLAttributes: иначе теряется
// проп invalid (красная рамка + aria-invalid) у числовых полей.
type NumberFieldProps = Omit<ComponentProps<typeof Input>, "type">;

export function NumberField(props: NumberFieldProps) {
  return <Input type="number" {...props} />;
}
