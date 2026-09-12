import { expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Switch } from "@/components/ui/Switch";

it("renders as a checkbox (native implicit role, not an explicit role override)", () => {
  render(<Switch aria-label="Напоминание" checked={false} onChange={() => {}} />);
  const field = screen.getByRole("checkbox", { name: "Напоминание" });
  expect(field).not.toBeChecked();
});

it("forwards toggle changes", () => {
  const onChange = vi.fn();
  render(<Switch aria-label="Напоминание" checked={false} onChange={onChange} />);
  fireEvent.click(screen.getByRole("checkbox", { name: "Напоминание" }));
  expect(onChange).toHaveBeenCalledOnce();
});
