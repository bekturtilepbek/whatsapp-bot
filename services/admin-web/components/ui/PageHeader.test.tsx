import { expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { PageHeader } from "@/components/ui/PageHeader";

it("renders the title as a heading", () => {
  render(<PageHeader title="Боты" />);
  expect(screen.getByRole("heading", { name: "Боты" })).toBeInTheDocument();
});

it("renders an optional subtitle and action", () => {
  render(<PageHeader title="Боты" subtitle="5 ботов" action={<button>Добавить</button>} />);
  expect(screen.getByText("5 ботов")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Добавить" })).toBeInTheDocument();
});

it("omits the subtitle element when none is given", () => {
  render(<PageHeader title="Боты" />);
  expect(screen.queryByText("5 ботов")).not.toBeInTheDocument();
});
