import { expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Card } from "@/components/ui/Card";

it("renders its children", () => {
  render(<Card>Содержимое карточки</Card>);
  expect(screen.getByText("Содержимое карточки")).toBeInTheDocument();
});

it("merges a caller className with its own", () => {
  render(<Card className="custom-class">X</Card>);
  expect(screen.getByText("X")).toHaveClass("custom-class");
});
