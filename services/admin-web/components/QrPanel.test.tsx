import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@/lib/test-utils";
import { QrPanel } from "@/components/QrPanel";
import * as api from "@/lib/api";
import type { Bot } from "@/lib/api";

const refreshMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: refreshMock }),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    fetchBot: vi.fn(),
    logoutBot: vi.fn(),
    patchBotEnabled: vi.fn(),
  };
});

const unlinkedBot: Bot = {
  id: "1",
  name: "Bot",
  enabled: true,
  phone: null,
  linked_at: null,
  system_prompt: "промпт",
  image_prompt: null,
  pdf_prompt: null,
};
const linkedBot: Bot = {
  id: "1",
  name: "Bot",
  enabled: true,
  phone: "996700000000",
  linked_at: "2026-09-09T00:00:00Z",
  system_prompt: "промпт",
  image_prompt: null,
  pdf_prompt: null,
};
const stats = { messages_count: 42, contacts_count: 7 };

afterEach(() => {
  vi.clearAllMocks();
});

it("shows the QR image while the bot is not linked", () => {
  render(
    <QrPanel initialBot={unlinkedBot} apiBaseUrl="http://api" stats={stats} pollIntervalMs={10000} />,
  );
  expect(screen.getByRole("img", { name: /qr/i })).toBeInTheDocument();
  expect(screen.queryByText(/отключить/i)).not.toBeInTheDocument();
});

it("renders the message/contact stat tiles alongside the QR panel (old project's layout: stats+toggle left, QR right)", () => {
  render(
    <QrPanel initialBot={unlinkedBot} apiBaseUrl="http://api" stats={stats} pollIntervalMs={10000} />,
  );
  expect(screen.getByText("42")).toBeInTheDocument();
  expect(screen.getByText("Сообщений всего")).toBeInTheDocument();
  expect(screen.getByText("7")).toBeInTheDocument();
  expect(screen.getByText("Контактов")).toBeInTheDocument();
});

it("shows a loading placeholder until the QR image actually finishes loading over the network", () => {
  // Пользователь сообщил: при переключении между ботами на месте QR
  // несколько секунд пусто — из-за того, что спиннер раньше гасился, как
  // только появлялся URL картинки (мгновенно), а не когда браузер реально
  // ЗАКОНЧИЛ её грузить (пока gateway лениво поднимает сессию для бота,
  // который давно не открывали, это реально занимает пару секунд).
  render(<QrPanel initialBot={unlinkedBot} apiBaseUrl="http://api" stats={stats} pollIntervalMs={10000} />);

  const img = screen.getByRole("img", { name: /qr/i });
  expect(screen.getByRole("status", { name: /загружаем qr/i })).toBeInTheDocument();
  expect(screen.getByText(/ожидание qr-кода/i)).toBeInTheDocument();

  fireEvent.load(img);

  expect(screen.queryByRole("status", { name: /загружаем qr/i })).not.toBeInTheDocument();
  expect(screen.queryByText(/ожидание qr-кода/i)).not.toBeInTheDocument();
});

it("switches to the connected view once polling finds linked_at set", async () => {
  vi.mocked(api.fetchBot).mockResolvedValue(linkedBot);
  render(<QrPanel initialBot={unlinkedBot} apiBaseUrl="http://api" stats={stats} pollIntervalMs={20} />);

  await waitFor(() => {
    expect(screen.getByText(/996700000000/)).toBeInTheDocument();
  });
  expect(screen.queryByRole("img", { name: /qr/i })).not.toBeInTheDocument();
});

it("shows an 'Открыть чат' link to wa.me for a connected bot", () => {
  render(<QrPanel initialBot={linkedBot} apiBaseUrl="http://api" stats={stats} pollIntervalMs={10000} />);

  const link = screen.getByRole("link", { name: /открыть чат/i });
  expect(link).toHaveAttribute("href", "https://wa.me/996700000000");
  expect(link).toHaveAttribute("target", "_blank");
});

it("logs out and returns to the QR view", async () => {
  vi.mocked(api.fetchBot).mockResolvedValue(unlinkedBot);
  vi.mocked(api.logoutBot).mockResolvedValue(undefined);
  render(<QrPanel initialBot={linkedBot} apiBaseUrl="http://api" stats={stats} pollIntervalMs={10000} />);

  fireEvent.click(screen.getByRole("button", { name: /отключить/i }));

  await waitFor(() => {
    expect(api.logoutBot).toHaveBeenCalledWith("http://api", "1");
  });
  await waitFor(() => {
    expect(screen.getByRole("img", { name: /qr/i })).toBeInTheDocument();
  });
  // getByRole("status") теперь неоднозначен — QR-заглушка загрузки тоже
  // им пользуется (см. тест выше); доступное имя тоста вычисляется пустым
  // (текст лежит в соседнем узле, не в aria-label), поэтому проверяем
  // текстом, не ролью+именем.
  expect(screen.getByText(/номер отключён/i)).toBeInTheDocument();
});

it("shows an error when a poll fails", async () => {
  vi.mocked(api.fetchBot).mockRejectedValue(new Error("network error"));
  render(<QrPanel initialBot={unlinkedBot} apiBaseUrl="http://api" stats={stats} pollIntervalMs={20} />);

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent(/network error/i);
  });
});

it("shows an error toast when logout fails", async () => {
  // Ошибка logout теперь идёт в toast (одноразовое действие), а не в
  // локальный error, завязанный на poll — гонка с refresh()'ом, успешно
  // чистившим error через setError(null), больше не существует: toast и
  // poll-статус (pollError) — независимые состояния.
  vi.mocked(api.logoutBot).mockRejectedValue(new Error("gateway unreachable"));
  vi.mocked(api.fetchBot).mockResolvedValue(linkedBot);
  render(<QrPanel initialBot={linkedBot} apiBaseUrl="http://api" stats={stats} pollIntervalMs={10000} />);

  fireEvent.click(screen.getByRole("button", { name: /отключить/i }));

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent(/gateway unreachable/i);
  });
});

it("toggles bot.enabled via the banner switch", async () => {
  const pausedBot = { ...linkedBot, enabled: false };
  const afterToggle = { ...linkedBot, enabled: true };
  vi.mocked(api.patchBotEnabled).mockResolvedValue(afterToggle);
  render(<QrPanel initialBot={pausedBot} apiBaseUrl="http://api" stats={stats} pollIntervalMs={10000} />);

  expect(screen.getByText(/бот на паузе/i)).toBeInTheDocument();

  fireEvent.click(screen.getByRole("checkbox", { name: /бот активен/i }));

  await waitFor(() => {
    expect(api.patchBotEnabled).toHaveBeenCalledWith("http://api", "1", true);
  });
  expect(screen.getByText(/бот активен — отвечает/i)).toBeInTheDocument();
  expect(refreshMock).toHaveBeenCalled();
});

it("shows an error toast when toggling bot.enabled fails", async () => {
  vi.mocked(api.patchBotEnabled).mockRejectedValue(new Error("update failed"));
  render(<QrPanel initialBot={linkedBot} apiBaseUrl="http://api" stats={stats} pollIntervalMs={10000} />);

  fireEvent.click(screen.getByRole("checkbox", { name: /бот активен/i }));

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent(/update failed/i);
  });
  expect(refreshMock).not.toHaveBeenCalled();
});

it("hides the disconnect button for a role without connection management (client)", () => {
  render(
    <QrPanel
      initialBot={linkedBot}
      apiBaseUrl="http://api"
      stats={stats}
      pollIntervalMs={10000}
      canManageConnection={false}
    />,
  );
  expect(screen.getByText(/996700000000/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /отключить/i })).not.toBeInTheDocument();
});

it("hides the QR scan card for a role without connection management (client) when not yet linked", () => {
  render(
    <QrPanel
      initialBot={unlinkedBot}
      apiBaseUrl="http://api"
      stats={stats}
      pollIntervalMs={10000}
      canManageConnection={false}
    />,
  );
  expect(screen.queryByRole("img", { name: /qr/i })).not.toBeInTheDocument();
  expect(screen.getByText(/не подключён/i)).toBeInTheDocument();
});
