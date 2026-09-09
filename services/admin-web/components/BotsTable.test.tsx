import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { BotsTable } from "@/components/BotsTable";
import type { Bot } from "@/lib/api";

const bots: Bot[] = [
  {
    id: "1",
    name: "Линкованный",
    enabled: true,
    phone: "996700000000",
    linked_at: "2026-09-09T00:00:00Z",
  },
  { id: "2", name: "Не линкованный", enabled: true, phone: null, linked_at: null },
];

it("shows status and phone for each bot", () => {
  render(<BotsTable bots={bots} />);
  expect(screen.getByText("Подключён")).toBeInTheDocument();
  expect(screen.getByText("996700000000")).toBeInTheDocument();
  expect(screen.getByText("Не подключён")).toBeInTheDocument();
  expect(screen.getByText("—")).toBeInTheDocument();
});

it("links to the bot detail page", () => {
  render(<BotsTable bots={bots} />);
  const link = screen.getAllByRole("link", { name: /открыть/i })[0];
  expect(link).toHaveAttribute("href", "/bots/1");
});
