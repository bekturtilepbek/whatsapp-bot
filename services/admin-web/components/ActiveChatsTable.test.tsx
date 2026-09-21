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
