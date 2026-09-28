import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import BotSettingsPage from "@/app/bots/[id]/settings/page";
import { fetchBot, fetchBotTools, fetchPrompters, type Bot } from "@/lib/api";
import { fetchCurrentUser } from "@/lib/currentUser";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, fetchBot: vi.fn(), fetchBotTools: vi.fn(), fetchPrompters: vi.fn() };
});
// PLATFORM_WIDE_ROLES остаётся реальным — страница использует его, чтобы
// решить, кому можно звать fetchPrompters (PlatformWide-only на бэкенде).
vi.mock("@/lib/currentUser", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/currentUser")>();
  return { ...actual, fetchCurrentUser: vi.fn() };
});
vi.mock("@/lib/env", () => ({
  API_INTERNAL_URL: "http://api.internal",
  API_PROXY_PATH: "/api-proxy",
}));
// Дочерние формы используют useToast() (нужен ToastProvider) — не то, что
// проверяет этот тест (гейт fetchPrompters/секции "Ответственный" по роли),
// поэтому заглушены, как QrPanel в соседнем app/bots/[id]/page.test.tsx.
vi.mock("@/components/RenameBotForm", () => ({ RenameBotForm: () => <div /> }));
vi.mock("@/components/ResponsibleUserForm", () => ({
  ResponsibleUserForm: () => <div data-testid="responsible-user-form" />,
}));
vi.mock("@/components/BotSettingsForm", () => ({ BotSettingsForm: () => <div /> }));
vi.mock("@/components/TelegramLeadToolForm", () => ({ TelegramLeadToolForm: () => <div /> }));

const mockedFetchBot = vi.mocked(fetchBot);
const mockedFetchBotTools = vi.mocked(fetchBotTools);
const mockedFetchPrompters = vi.mocked(fetchPrompters);
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

// Живой баг (security review, 2026-09-28): GET /users/prompters — PlatformWide-
// only (superadmin/admin), но страница звала его для ЛЮБОЙ не-client роли,
// включая prompter (у которого есть полный доступ к боту, но НЕ платформенный
// охват) — 403 от api приводил к необработанному краху страницы.
it("does not call fetchPrompters and hides the Ответственный card for a prompter", async () => {
  mockedFetchBot.mockResolvedValue(bot);
  mockedFetchBotTools.mockResolvedValue([]);
  mockedFetchCurrentUser.mockResolvedValue({ email: "prompter@example.com", role: "prompter" });

  const element = await BotSettingsPage({ params: Promise.resolve({ id: "1" }) });
  render(element);

  expect(mockedFetchPrompters).not.toHaveBeenCalled();
  expect(screen.queryByTestId("responsible-user-form")).not.toBeInTheDocument();
});

it("calls fetchPrompters and shows the Ответственный card for an admin", async () => {
  mockedFetchBot.mockResolvedValue(bot);
  mockedFetchBotTools.mockResolvedValue([]);
  mockedFetchPrompters.mockResolvedValue([]);
  mockedFetchCurrentUser.mockResolvedValue({ email: "admin@example.com", role: "admin" });

  const element = await BotSettingsPage({ params: Promise.resolve({ id: "1" }) });
  render(element);

  expect(mockedFetchPrompters).toHaveBeenCalled();
  expect(screen.getByTestId("responsible-user-form")).toBeInTheDocument();
});

it("calls fetchPrompters and shows the Ответственный card for a superadmin", async () => {
  mockedFetchBot.mockResolvedValue(bot);
  mockedFetchBotTools.mockResolvedValue([]);
  mockedFetchPrompters.mockResolvedValue([]);
  mockedFetchCurrentUser.mockResolvedValue({ email: "owner@example.com", role: "superadmin" });

  const element = await BotSettingsPage({ params: Promise.resolve({ id: "1" }) });
  render(element);

  expect(mockedFetchPrompters).toHaveBeenCalled();
  expect(screen.getByTestId("responsible-user-form")).toBeInTheDocument();
});
