import { expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Textarea } from "@/components/ui/Textarea";

it("renders with the given placeholder and forwards typing", () => {
  const onChange = vi.fn();
  render(<Textarea placeholder="Промпт" onChange={onChange} />);
  const field = screen.getByPlaceholderText("Промпт");
  fireEvent.change(field, { target: { value: "Ты — помощник" } });
  expect(onChange).toHaveBeenCalledOnce();
});
