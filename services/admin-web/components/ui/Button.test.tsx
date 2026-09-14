import { expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Button } from "@/components/ui/Button";

it("renders its children as the accessible name", () => {
  render(<Button>Сохранить</Button>);
  expect(screen.getByRole("button", { name: "Сохранить" })).toBeInTheDocument();
});

it("calls onClick when clicked", () => {
  const onClick = vi.fn();
  render(<Button onClick={onClick}>Сохранить</Button>);
  fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
  expect(onClick).toHaveBeenCalledOnce();
});

it("does not fire onClick when disabled", () => {
  const onClick = vi.fn();
  render(
    <Button onClick={onClick} disabled>
      Сохранить
    </Button>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
  expect(onClick).not.toHaveBeenCalled();
});

it("forwards the native type attribute", () => {
  render(<Button type="submit">Отправить</Button>);
  expect(screen.getByRole("button", { name: "Отправить" })).toHaveAttribute("type", "submit");
});

it("renders every variant without crashing", () => {
  const { rerender } = render(<Button variant="primary">A</Button>);
  expect(screen.getByRole("button")).toBeInTheDocument();
  rerender(<Button variant="secondary">A</Button>);
  expect(screen.getByRole("button")).toBeInTheDocument();
  rerender(<Button variant="danger">A</Button>);
  expect(screen.getByRole("button")).toBeInTheDocument();
});
