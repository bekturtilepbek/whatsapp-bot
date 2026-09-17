import { expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { IconBadge } from "@/components/ui/IconBadge";

it("renders its icon child", () => {
  render(
    <IconBadge variant="success">
      <svg role="img" aria-label="Готово" />
    </IconBadge>,
  );
  expect(screen.getByRole("img", { name: "Готово" })).toBeInTheDocument();
});

it("renders every variant without crashing", () => {
  const { rerender } = render(<IconBadge variant="success">x</IconBadge>);
  expect(screen.getByText("x")).toBeInTheDocument();
  rerender(<IconBadge variant="accent">x</IconBadge>);
  expect(screen.getByText("x")).toBeInTheDocument();
  rerender(<IconBadge variant="warning">x</IconBadge>);
  expect(screen.getByText("x")).toBeInTheDocument();
  rerender(<IconBadge variant="danger">x</IconBadge>);
  expect(screen.getByText("x")).toBeInTheDocument();
});

it("merges a caller className with its own", () => {
  render(
    <IconBadge className="custom-class">
      <svg role="img" aria-label="X" />
    </IconBadge>,
  );
  expect(screen.getByRole("img", { name: "X" }).parentElement).toHaveClass("custom-class");
});
