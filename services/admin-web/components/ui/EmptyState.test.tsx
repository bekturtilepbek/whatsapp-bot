import { expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { EmptyState } from "@/components/ui/EmptyState";

it("renders the title, description and action", () => {
  render(
    <EmptyState
      title="Товаров пока нет"
      description="Добавьте первый товар"
      action={<button>Добавить товар</button>}
    />,
  );
  expect(screen.getByText("Товаров пока нет")).toBeInTheDocument();
  expect(screen.getByText("Добавьте первый товар")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Добавить товар" })).toBeInTheDocument();
});

it("omits description and action when not given", () => {
  render(<EmptyState title="Товаров пока нет" />);
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});
