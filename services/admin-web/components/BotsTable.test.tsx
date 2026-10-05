import { expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: pushMock }) }));
import { BotsTable } from "@/components/BotsTable";
import type { Bot } from "@/lib/api";

const bots: Bot[] = [
  {
    id: "1",
    name: "Линкованный",
    enabled: true,
    phone: "996700000000",
    linked_at: "2026-09-09T00:00:00Z",
    system_prompt: "промпт",
    image_prompt: null,
    pdf_prompt: null,
  },
  {
    id: "2",
    name: "Не линкованный",
    enabled: true,
    phone: null,
    linked_at: null,
    system_prompt: "промпт",
    image_prompt: null,
    pdf_prompt: null,
  },
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

// 2026-09-30: бота можно открыть кликом по любой ячейке строки, не только
// по ссылке "Открыть".
it("opens the bot when any cell of its row is clicked", () => {
  pushMock.mockClear();
  render(<BotsTable bots={bots} />);
  fireEvent.click(screen.getByText("996700000000"));
  expect(pushMock).toHaveBeenCalledWith("/bots/1");
});

it("leaves clicks on the link itself to the link (no double navigation)", () => {
  pushMock.mockClear();
  render(<BotsTable bots={bots} />);
  fireEvent.click(screen.getAllByRole("link", { name: /открыть/i })[0]);
  expect(pushMock).not.toHaveBeenCalled();
});

it("shows an explanatory message instead of a table when there are no bots", () => {
  render(<BotsTable bots={[]} />);
  expect(
    screen.getByText("Доступа пока нет, обратитесь к владельцу платформы")
  ).toBeInTheDocument();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});

it("shows a paused badge for a disabled bot", () => {
  const paused: Bot[] = [{ ...bots[0], enabled: false }];
  render(<BotsTable bots={paused} />);
  expect(screen.getByText("на паузе")).toBeInTheDocument();
});

it("shows the disconnected status for a bot mid-connection", () => {
  const pending: Bot[] = [{ ...bots[0], status: "qr", linked_at: null }];
  render(<BotsTable bots={pending} />);
  expect(screen.getByText("Не подключён")).toBeInTheDocument();
});

// 6.22: служебный статус клиента приходит только для superadmin/admin.
it("shows the lifecycle status badge when the field is present", () => {
  render(<BotsTable bots={[{ ...bots[0], lifecycle_status: "unpaid" }]} />);
  expect(screen.getByText("Не оплачен")).toBeInTheDocument();
});

it("shows no lifecycle badge when the field is absent or null", () => {
  render(<BotsTable bots={[{ ...bots[0], lifecycle_status: null }, bots[1]]} />);
  expect(screen.queryByText("В разработке")).not.toBeInTheDocument();
  expect(screen.queryByText("Заморожен")).not.toBeInTheDocument();
  expect(screen.queryByText("Не оплачен")).not.toBeInTheDocument();
});
