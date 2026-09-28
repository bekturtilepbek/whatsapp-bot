import { fireEvent, render, screen } from "@testing-library/react";
import { it, expect } from "vitest";
import { BotsSearch } from "@/components/BotsSearch";
import type { Bot } from "@/lib/api";

const connectedBot: Bot = {
  id: "1",
  name: "Кофейня",
  enabled: true,
  phone: "996700000000",
  linked_at: "2026-09-09T00:00:00Z",
  system_prompt: "промпт",
  image_prompt: null,
  pdf_prompt: null,
};

const disconnectedBot: Bot = {
  id: "2",
  name: "Магазин",
  enabled: true,
  phone: null,
  linked_at: null,
  system_prompt: "промпт",
  image_prompt: null,
  pdf_prompt: null,
};

const bots = [connectedBot, disconnectedBot];

it("shows both bots by default", () => {
  render(<BotsSearch bots={bots} />);
  expect(screen.getByText("Кофейня")).toBeInTheDocument();
  expect(screen.getByText("Магазин")).toBeInTheDocument();
});

it("filters by name via the search input", () => {
  render(<BotsSearch bots={bots} />);
  fireEvent.change(screen.getByLabelText("Поиск ботов"), { target: { value: "кофе" } });
  expect(screen.getByText("Кофейня")).toBeInTheDocument();
  expect(screen.queryByText("Магазин")).not.toBeInTheDocument();
});

it("filters by connection status", () => {
  render(<BotsSearch bots={bots} />);
  fireEvent.change(screen.getByLabelText("Фильтр по статусу подключения"), {
    target: { value: "connected" },
  });
  expect(screen.getByText("Кофейня")).toBeInTheDocument();
  expect(screen.queryByText("Магазин")).not.toBeInTheDocument();
});

it("combines the status filter with the search query", () => {
  render(<BotsSearch bots={bots} />);
  fireEvent.change(screen.getByLabelText("Фильтр по статусу подключения"), {
    target: { value: "disconnected" },
  });
  fireEvent.change(screen.getByLabelText("Поиск ботов"), { target: { value: "кофе" } });
  expect(screen.getByText("Ничего не найдено")).toBeInTheDocument();
});

it("shows an empty state when the status filter matches nothing", () => {
  render(<BotsSearch bots={[connectedBot]} />);
  fireEvent.change(screen.getByLabelText("Фильтр по статусу подключения"), {
    target: { value: "disconnected" },
  });
  expect(screen.getByText("Ничего не найдено")).toBeInTheDocument();
});
