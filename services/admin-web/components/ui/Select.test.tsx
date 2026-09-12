import { expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Select } from "@/components/ui/Select";

it("renders its options and forwards selection changes", () => {
  const onChange = vi.fn();
  render(
    <Select aria-label="Период" onChange={onChange}>
      <option value="7d">7 дней</option>
      <option value="30d">30 дней</option>
    </Select>,
  );
  const field = screen.getByLabelText("Период");
  fireEvent.change(field, { target: { value: "30d" } });
  expect(onChange).toHaveBeenCalledOnce();
  expect(screen.getByRole("option", { name: "30 дней" })).toBeInTheDocument();
});
