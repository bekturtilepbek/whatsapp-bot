import { afterEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@/lib/test-utils";
import { AuditLogTable } from "@/components/AuditLogTable";
import * as api from "@/lib/api";
import type { AuditLogEntry, Bot } from "@/lib/api";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    fetchAuditLog: vi.fn(),
  };
});

const bots: Bot[] = [
  {
    id: "bot-1",
    name: "Bot One",
    enabled: true,
    phone: null,
    linked_at: null,
    system_prompt: "",
    image_prompt: null,
    pdf_prompt: null,
  },
];

const entries: AuditLogEntry[] = [
  {
    id: "e1",
    actor_user_id: "u1",
    actor_email: "owner@example.com",
    bot_id: "bot-1",
    bot_name: "Bot One",
    action: "bots.update",
    payload: { name: "Новое имя" },
    created_at: "2026-09-11T10:00:00Z",
  },
];

afterEach(() => {
  vi.clearAllMocks();
});

it("renders each entry's actor, bot and action", () => {
  render(<AuditLogTable apiBaseUrl="http://api" entries={entries} bots={bots} pageSize={50} />);
  expect(screen.getByText("owner@example.com")).toBeInTheDocument();
  // "Bot One" появляется и в <option> фильтра, и в ячейке таблицы — сужаем
  // до ячейки (селектор td), иначе getByText находит два совпадения.
  expect(screen.getByText("Bot One", { selector: "td" })).toBeInTheDocument();
  expect(screen.getByText("bots.update")).toBeInTheDocument();
});

it("shows the payload when the details element is expanded", () => {
  render(<AuditLogTable apiBaseUrl="http://api" entries={entries} bots={bots} pageSize={50} />);
  expect(screen.getByText(/новое имя/i)).toBeInTheDocument();
});

it("refetches with the selected bot filter", async () => {
  vi.mocked(api.fetchAuditLog).mockResolvedValue([]);
  render(<AuditLogTable apiBaseUrl="http://api" entries={entries} bots={bots} pageSize={50} />);

  fireEvent.change(screen.getByLabelText("Фильтр по боту"), { target: { value: "bot-1" } });

  await waitFor(() => {
    expect(api.fetchAuditLog).toHaveBeenCalledWith("http://api", {
      botId: "bot-1",
      limit: 50,
    });
  });
});

it('hides "Показать ещё" when the first page is smaller than pageSize', () => {
  render(<AuditLogTable apiBaseUrl="http://api" entries={entries} bots={bots} pageSize={50} />);
  expect(screen.queryByRole("button", { name: /показать ещё/i })).not.toBeInTheDocument();
});

it('shows "Показать ещё", loads and appends the next page, then hides once exhausted', async () => {
  const fullPage: AuditLogEntry[] = [entries[0], { ...entries[0], id: "e2" }];
  vi.mocked(api.fetchAuditLog).mockResolvedValue([{ ...entries[0], id: "e3" }]);
  render(<AuditLogTable apiBaseUrl="http://api" entries={fullPage} bots={bots} pageSize={2} />);
  expect(screen.getByRole("button", { name: /показать ещё/i })).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: /показать ещё/i }));

  await waitFor(() => {
    expect(api.fetchAuditLog).toHaveBeenCalledWith("http://api", { botId: undefined, limit: 2, offset: 2 });
  });
  expect(screen.queryByRole("button", { name: /показать ещё/i })).not.toBeInTheDocument();
});

it("shows an error when loading more fails", async () => {
  vi.mocked(api.fetchAuditLog).mockRejectedValue(new Error("load failed"));
  const fullPage: AuditLogEntry[] = [entries[0], { ...entries[0], id: "e2" }];
  render(<AuditLogTable apiBaseUrl="http://api" entries={fullPage} bots={bots} pageSize={2} />);

  fireEvent.click(screen.getByRole("button", { name: /показать ещё/i }));

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent(/load failed/i);
  });
});

it("shows an empty state when there are no entries", () => {
  render(<AuditLogTable apiBaseUrl="http://api" entries={[]} bots={bots} pageSize={50} />);
  expect(screen.getByText("Записей аудит-лога пока нет")).toBeInTheDocument();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});
