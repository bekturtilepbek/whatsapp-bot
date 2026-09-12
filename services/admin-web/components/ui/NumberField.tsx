import type { InputHTMLAttributes } from "react";
import { Input } from "@/components/ui/Input";

type NumberFieldProps = Omit<InputHTMLAttributes<HTMLInputElement>, "type">;

export function NumberField(props: NumberFieldProps) {
  return <Input type="number" {...props} />;
}
