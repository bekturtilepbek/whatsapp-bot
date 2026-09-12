import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Input } from "@/components/ui/Input";

it("renders with the given placeholder and forwards typing", () => {
  const onChange = vi.fn();
  render(<Input placeholder="Название" onChange={onChange} />);
  const field = screen.getByPlaceholderText("Название");
  fireEvent.change(field, { target: { value: "Кофейня" } });
  expect(onChange).toHaveBeenCalledOnce();
});

it("forwards disabled and value", () => {
  render(<Input value="Кофейня" disabled onChange={() => {}} />);
  const field = screen.getByDisplayValue("Кофейня");
  expect(field).toBeDisabled();
});
