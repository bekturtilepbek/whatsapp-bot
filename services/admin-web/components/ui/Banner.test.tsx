import { expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Banner } from "@/components/ui/Banner";

it("renders the title, optional description and action", () => {
  render(
    <Banner
      icon={<svg aria-hidden="true" />}
      title="Бот активен — отвечает на сообщения"
      description="Входящие запросы обрабатываются автоматически"
      action={<button>Пауза</button>}
    />,
  );
  expect(screen.getByText("Бот активен — отвечает на сообщения")).toBeInTheDocument();
  expect(screen.getByText("Входящие запросы обрабатываются автоматически")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Пауза" })).toBeInTheDocument();
});

it("omits the description when not given", () => {
  render(<Banner icon={<svg aria-hidden="true" />} title="Бот на паузе" />);
  expect(screen.getByText("Бот на паузе")).toBeInTheDocument();
});

it("renders every variant without crashing", () => {
  const { rerender } = render(<Banner icon={<svg aria-hidden="true" />} title="x" variant="success" />);
  expect(screen.getByText("x")).toBeInTheDocument();
  rerender(<Banner icon={<svg aria-hidden="true" />} title="x" variant="accent" />);
  expect(screen.getByText("x")).toBeInTheDocument();
  rerender(<Banner icon={<svg aria-hidden="true" />} title="x" variant="warning" />);
  expect(screen.getByText("x")).toBeInTheDocument();
  rerender(<Banner icon={<svg aria-hidden="true" />} title="x" variant="danger" />);
  expect(screen.getByText("x")).toBeInTheDocument();
});
