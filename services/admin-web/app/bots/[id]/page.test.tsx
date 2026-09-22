import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import BotOverviewPage from "@/app/bots/[id]/page";
import { fetchBot, fetchBotStats, type Bot, type BotStats } from "@/lib/api";
import { fetchCurrentUser } from "@/lib/currentUser";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, fetchBot: vi.fn(), fetchBotStats: vi.fn() };
});
vi.mock("@/lib/currentUser", () => ({
  fetchCurrentUser: vi.fn(),
}));
vi.mock("@/lib/env", () => ({
  API_INTERNAL_URL: "http://api.internal",
  API_PROXY_PATH: "/api-proxy",
}));
// QrPanel — client-компонент со своим поллингом/интервалом и теперь своей
// стат-плиточной раскладкой (оба покрыты QrPanel.test.tsx отдельно) —
// здесь заглушка, показывающая только то, что реально дошло в props, чтобы
// проверить именно передачу stats/canManageConnection со страницы, а не их
// рендер.
vi.mock("@/components/QrPanel", () => ({
  QrPanel: ({ stats, canManageConnection }: { stats: BotStats; canManageConnection: boolean }) => (
    <div data-testid="qr-panel-stub">
      {stats.messages_count}/{stats.contacts_count}/{String(canManageConnection)}
    </div>
  ),
}));

const mockedFetchBot = vi.mocked(fetchBot);
const mockedFetchBotStats = vi.mocked(fetchBotStats);
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

const stats: BotStats = { messages_count: 1234, contacts_count: 56 };

it("fetches stats alongside the bot and passes them through to QrPanel", async () => {
  mockedFetchBot.mockResolvedValue(bot);
  mockedFetchBotStats.mockResolvedValue(stats);
  mockedFetchCurrentUser.mockResolvedValue({ email: "owner@example.com", role: "superadmin" });

  const element = await BotOverviewPage({ params: Promise.resolve({ id: "1" }) });
  render(element);

  expect(screen.getByTestId("qr-panel-stub")).toHaveTextContent("1234/56/true");
});

it("passes canManageConnection=false for a client", async () => {
  mockedFetchBot.mockResolvedValue(bot);
  mockedFetchBotStats.mockResolvedValue(stats);
  mockedFetchCurrentUser.mockResolvedValue({ email: "client@example.com", role: "client" });

  const element = await BotOverviewPage({ params: Promise.resolve({ id: "1" }) });
  render(element);

  expect(screen.getByTestId("qr-panel-stub")).toHaveTextContent("1234/56/false");
});

it("renders nothing when the bot is not found (notFound already handled in layout)", async () => {
  mockedFetchBot.mockResolvedValue(null);
  mockedFetchBotStats.mockResolvedValue(stats);
  mockedFetchCurrentUser.mockResolvedValue({ email: "owner@example.com", role: "superadmin" });

  const element = await BotOverviewPage({ params: Promise.resolve({ id: "missing" }) });

  expect(element).toBeNull();
});
