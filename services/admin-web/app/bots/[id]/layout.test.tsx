import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import BotLayout from "@/app/bots/[id]/layout";
import { fetchBot, type Bot } from "@/lib/api";
import { fetchCurrentUser } from "@/lib/currentUser";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, fetchBot: vi.fn() };
});
vi.mock("@/lib/currentUser", () => ({
  fetchCurrentUser: vi.fn(),
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
const mockedFetchCurrentUser = vi.mocked(fetchCurrentUser);

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

it("renders the bot name, connection status and every tab for a superadmin, including prompts/settings/blocked-numbers/sandbox", async () => {
  mockedFetchBot.mockResolvedValue(bot);
  mockedFetchCurrentUser.mockResolvedValue({ email: "owner@example.com", role: "superadmin" });
  const element = await BotLayout({
    params: Promise.resolve({ id: "1" }),
    children: <div>Содержимое вкладки</div>,
  });
  render(element);

  expect(screen.getByText("Кофейня «Аромат»")).toBeInTheDocument();
  expect(screen.getByText("Подключён")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Обзор" })).toHaveAttribute("href", "/bots/1");
  expect(screen.getByRole("link", { name: "Промпты" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Настройки" })).toHaveAttribute("href", "/bots/1/settings");
  expect(screen.getByRole("link", { name: "Чёрный список" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Песочница" })).toBeInTheDocument();
  expect(screen.getByText("Содержимое вкладки")).toBeInTheDocument();
});

it("shows every tab, including sandbox, for a prompter (full bot access, ролевой пересмотр 2026-09-22)", async () => {
  mockedFetchBot.mockResolvedValue(bot);
  mockedFetchCurrentUser.mockResolvedValue({ email: "prompter@example.com", role: "prompter" });
  const element = await BotLayout({
    params: Promise.resolve({ id: "1" }),
    children: <div>Содержимое вкладки</div>,
  });
  render(element);

  expect(screen.getByRole("link", { name: "Промпты" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Настройки" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Чёрный список" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Песочница" })).toBeInTheDocument();
});

it("hides prompts/settings/blocked-numbers, but keeps sandbox, for a client", async () => {
  mockedFetchBot.mockResolvedValue(bot);
  mockedFetchCurrentUser.mockResolvedValue({ email: "client@example.com", role: "client" });
  const element = await BotLayout({
    params: Promise.resolve({ id: "1" }),
    children: <div>Содержимое вкладки</div>,
  });
  render(element);

  expect(screen.queryByRole("link", { name: "Промпты" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Настройки" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Чёрный список" })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Товары" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Документы" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Активные чаты" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Песочница" })).toBeInTheDocument();
});

// render(await BotLayout({...})) резолвит только один уровень async —
// безопасно, пока ни один child BotLayout (сейчас — TabLink, синхронный
// client-компонент) не станет сам async Server Component-ом.

it("shows disconnected when the session is mid-connection", async () => {
  mockedFetchBot.mockResolvedValue({ ...bot, status: "qr" });
  mockedFetchCurrentUser.mockResolvedValue({ email: "owner@example.com", role: "superadmin" });
  const element = await BotLayout({
    params: Promise.resolve({ id: "1" }),
    children: <div>Содержимое вкладки</div>,
  });
  render(element);
  expect(screen.getByText("Не подключён")).toBeInTheDocument();
});

it("shows disconnected when linked but logged out, even though linked_at is still set", async () => {
  mockedFetchBot.mockResolvedValue({ ...bot, status: "logged_out" });
  mockedFetchCurrentUser.mockResolvedValue({ email: "owner@example.com", role: "superadmin" });
  const element = await BotLayout({
    params: Promise.resolve({ id: "1" }),
    children: <div>Содержимое вкладки</div>,
  });
  render(element);
  expect(screen.getByText("Не подключён")).toBeInTheDocument();
});
