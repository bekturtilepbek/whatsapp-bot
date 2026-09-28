import { afterEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@/lib/test-utils";
import { ActiveChatsTable } from "@/components/ActiveChatsTable";
import * as api from "@/lib/api";
import type { ActiveChat } from "@/lib/api";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, releaseChat: vi.fn() };
});

afterEach(() => {
  vi.clearAllMocks();
});

const namedChat: ActiveChat = {
  chat_id: "996700000001@s.whatsapp.net",
  contact_name: "Айгуль",
  contact_phone: null,
  auto_release_in_seconds: 500,
};

const unnamedChat: ActiveChat = {
  chat_id: "996700000002@s.whatsapp.net",
  contact_name: null,
  contact_phone: null,
  auto_release_in_seconds: null,
};

it("shows an empty state when there are no active chats", () => {
  render(<ActiveChatsTable botId="1" apiBaseUrl="http://api" initialChats={[]} />);
  expect(screen.getByText("Нет активных чатов с участием человека")).toBeInTheDocument();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});

it("shows the contact name when known, and the raw JID user-part when not", () => {
  render(
    <ActiveChatsTable botId="1" apiBaseUrl="http://api" initialChats={[namedChat, unnamedChat]} />,
  );
  expect(screen.getByText("Айгуль")).toBeInTheDocument();
  expect(screen.getByText("996700000002")).toBeInTheDocument();
});

it("shows a rounded-up minutes estimate for the auto-release TTL, or a dash when unknown", () => {
  render(
    <ActiveChatsTable botId="1" apiBaseUrl="http://api" initialChats={[namedChat, unnamedChat]} />,
  );
  expect(screen.getByText("~9 мин")).toBeInTheDocument(); // 500с -> ceil(500/60) = 9
  expect(screen.getByText("—")).toBeInTheDocument();
});

it("releases a chat and removes it from the list on success", async () => {
  vi.mocked(api.releaseChat).mockResolvedValue(undefined);
  render(<ActiveChatsTable botId="1" apiBaseUrl="http://api" initialChats={[namedChat]} />);

  fireEvent.click(screen.getByRole("button", { name: /освободить/i }));

  await waitFor(() => {
    expect(api.releaseChat).toHaveBeenCalledWith(
      "http://api",
      "1",
      "996700000001@s.whatsapp.net",
    );
  });
  expect(await screen.findByText("Нет активных чатов с участием человека")).toBeInTheDocument();
});

it("shows an error toast and keeps the row when releasing fails", async () => {
  vi.mocked(api.releaseChat).mockRejectedValue(new Error("release failed"));
  render(<ActiveChatsTable botId="1" apiBaseUrl="http://api" initialChats={[namedChat]} />);

  fireEvent.click(screen.getByRole("button", { name: /освободить/i }));

  expect(await screen.findByRole("alert")).toHaveTextContent(/release failed/i);
  expect(screen.getByText("Айгуль")).toBeInTheDocument();
});

it("filters by contact via the search input", () => {
  render(
    <ActiveChatsTable botId="1" apiBaseUrl="http://api" initialChats={[namedChat, unnamedChat]} />,
  );

  fireEvent.change(screen.getByLabelText("Поиск активных чатов"), {
    target: { value: "Айгуль" },
  });

  expect(screen.getByText("Айгуль")).toBeInTheDocument();
  expect(screen.queryByText("996700000002")).not.toBeInTheDocument();
});

it("sorts by auto-release time when its header is clicked", () => {
  render(
    <ActiveChatsTable botId="1" apiBaseUrl="http://api" initialChats={[namedChat, unnamedChat]} />,
  );

  fireEvent.click(screen.getByRole("button", { name: /авто-возврат/i }));
  // unnamedChat.auto_release_in_seconds === null -> трактуется как "без
  // ограничения" (Infinity), значит уходит в конец при сортировке по
  // возрастанию — Айгуль (500с) должна быть первой строкой.
  const cells = screen.getAllByRole("row").slice(1).map((row) => row.textContent);
  expect(cells[0]).toContain("Айгуль");
});
