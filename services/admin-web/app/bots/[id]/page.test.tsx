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
// QrPanel — client-компонент со своим поллингом/интервалом и теперь своей
// стат-плиточной раскладкой (оба покрыты QrPanel.test.tsx отдельно) —
// здесь заглушка, показывающая только то, что реально дошло в props, чтобы
// проверить именно передачу stats со страницы, а не их рендер.
vi.mock("@/components/QrPanel", () => ({
  QrPanel: ({ stats }: { stats: BotStats }) => (
    <div data-testid="qr-panel-stub">
      {stats.messages_count}/{stats.contacts_count}
    </div>
  ),
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

it("fetches stats alongside the bot and passes them through to QrPanel", async () => {
  mockedFetchBot.mockResolvedValue(bot);
  mockedFetchBotStats.mockResolvedValue(stats);

  const element = await BotOverviewPage({ params: Promise.resolve({ id: "1" }) });
  render(element);

  expect(screen.getByTestId("qr-panel-stub")).toHaveTextContent("1234/56");
});

it("renders nothing when the bot is not found (notFound already handled in layout)", async () => {
  mockedFetchBot.mockResolvedValue(null);
  mockedFetchBotStats.mockResolvedValue(stats);

  const element = await BotOverviewPage({ params: Promise.resolve({ id: "missing" }) });

  expect(element).toBeNull();
});
