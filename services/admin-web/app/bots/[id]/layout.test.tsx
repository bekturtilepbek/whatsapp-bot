import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import BotLayout from "@/app/bots/[id]/layout";
import { fetchBot, type Bot } from "@/lib/api";
import { currentUserIsOwner } from "@/lib/currentUser";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, fetchBot: vi.fn() };
});
vi.mock("@/lib/currentUser", () => ({
  currentUserIsOwner: vi.fn(),
}));
vi.mock("@/lib/env", () => ({
  API_INTERNAL_URL: "http://api.internal",
}));
// TabLink (Task 6) calls usePathname() — outside a Next.js router context
// (as in this render) it returns null, not a string, which crashes
// TabLink's pathname.startsWith(href). Mocked here the same way
// components/ui/TabLink.test.tsx already does; notFound stays real via
// importOriginal since layout.tsx also imports it (unused on the happy path
// these two tests exercise).
vi.mock("next/navigation", async (importOriginal) => {
  const actual = await importOriginal<typeof import("next/navigation")>();
  return { ...actual, usePathname: () => "/bots/1" };
});

const mockedFetchBot = vi.mocked(fetchBot);
const mockedIsOwner = vi.mocked(currentUserIsOwner);

const bot: Bot = {
  id: "1",
  name: "Кофейня «Аромат»",
  enabled: true,
  phone: "996700000000",
  linked_at: "2026-09-01T00:00:00Z",
  system_prompt: "промпт",
  image_prompt: null,
  pdf_prompt: null,
};

it("renders the bot name, connection status and every tab, including the sandbox tab for the owner", async () => {
  mockedFetchBot.mockResolvedValue(bot);
  mockedIsOwner.mockResolvedValue(true);
  const element = await BotLayout({
    params: Promise.resolve({ id: "1" }),
    children: <div>Содержимое вкладки</div>,
  });
  render(element);

  expect(screen.getByText("Кофейня «Аромат»")).toBeInTheDocument();
  expect(screen.getByText("Подключён")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Обзор" })).toHaveAttribute("href", "/bots/1");
  expect(screen.getByRole("link", { name: "Настройки" })).toHaveAttribute("href", "/bots/1/settings");
  expect(screen.getByRole("link", { name: "Песочница" })).toBeInTheDocument();
  expect(screen.getByText("Содержимое вкладки")).toBeInTheDocument();
});

it("hides the sandbox tab for a non-owner", async () => {
  mockedFetchBot.mockResolvedValue(bot);
  mockedIsOwner.mockResolvedValue(false);
  const element = await BotLayout({
    params: Promise.resolve({ id: "1" }),
    children: <div>Содержимое вкладки</div>,
  });
  render(element);
  expect(screen.queryByRole("link", { name: "Песочница" })).not.toBeInTheDocument();
});

// render(await BotLayout({...})) резолвит только один уровень async —
// безопасно, пока ни один child BotLayout (сейчас — TabLink, синхронный
// client-компонент) не станет сам async Server Component-ом.

it("shows disconnected when the session is mid-connection", async () => {
  mockedFetchBot.mockResolvedValue({ ...bot, status: "qr" });
  mockedIsOwner.mockResolvedValue(true);
  const element = await BotLayout({
    params: Promise.resolve({ id: "1" }),
    children: <div>Содержимое вкладки</div>,
  });
  render(element);
  expect(screen.getByText("Не подключён")).toBeInTheDocument();
});

it("shows disconnected when linked but logged out, even though linked_at is still set", async () => {
  mockedFetchBot.mockResolvedValue({ ...bot, status: "logged_out" });
  mockedIsOwner.mockResolvedValue(true);
  const element = await BotLayout({
    params: Promise.resolve({ id: "1" }),
    children: <div>Содержимое вкладки</div>,
  });
  render(element);
  expect(screen.getByText("Не подключён")).toBeInTheDocument();
});
