import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import BotOverviewPage from "@/app/bots/[id]/page";
import { fetchBot, fetchBotStats, type Bot, type BotStats } from "@/lib/api";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, fetchBot: vi.fn(), fetchBotStats: vi.fn() };
});
vi.mock("@/lib/env", () => ({
  API_INTERNAL_URL: "http://api.internal",
  API_PROXY_PATH: "/api-proxy",
}));
// QrPanel — client-компонент со своим поллингом/интервалом (уже покрыт
// QrPanel.test.tsx отдельно) — здесь заглушка, эта страница проверяет
// только стат-плитки над ним.
vi.mock("@/components/QrPanel", () => ({
  QrPanel: () => <div data-testid="qr-panel-stub" />,
}));

const mockedFetchBot = vi.mocked(fetchBot);
const mockedFetchBotStats = vi.mocked(fetchBotStats);

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

it("renders message and contact count tiles above the QR panel", async () => {
  mockedFetchBot.mockResolvedValue(bot);
  mockedFetchBotStats.mockResolvedValue(stats);

  const element = await BotOverviewPage({ params: Promise.resolve({ id: "1" }) });
  render(element);

  expect(screen.getByText("1 234")).toBeInTheDocument();
  expect(screen.getByText("Сообщений всего")).toBeInTheDocument();
  expect(screen.getByText("56")).toBeInTheDocument();
  expect(screen.getByText("Контактов")).toBeInTheDocument();
  expect(screen.getByTestId("qr-panel-stub")).toBeInTheDocument();
});

it("renders nothing when the bot is not found (notFound already handled in layout)", async () => {
  mockedFetchBot.mockResolvedValue(null);
  mockedFetchBotStats.mockResolvedValue(stats);

  const element = await BotOverviewPage({ params: Promise.resolve({ id: "missing" }) });

  expect(element).toBeNull();
});
