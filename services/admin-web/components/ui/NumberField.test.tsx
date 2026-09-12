import { expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { NumberField } from "@/components/ui/NumberField";

it("renders as a native number input", () => {
  render(<NumberField aria-label="Таймаут батчинга" value={1} onChange={() => {}} />);
  const field = screen.getByLabelText("Таймаут батчинга");
  expect(field).toHaveAttribute("type", "number");
});
