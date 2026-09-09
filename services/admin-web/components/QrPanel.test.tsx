import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QrPanel } from "@/components/QrPanel";
import * as api from "@/lib/api";
import type { Bot } from "@/lib/api";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    fetchBot: vi.fn(),
    logoutBot: vi.fn(),
  };
});

const unlinkedBot: Bot = { id: "1", name: "Bot", enabled: true, phone: null, linked_at: null };
const linkedBot: Bot = {
  id: "1",
  name: "Bot",
  enabled: true,
  phone: "996700000000",
  linked_at: "2026-09-09T00:00:00Z",
};

afterEach(() => {
  vi.clearAllMocks();
});

it("shows the QR image while the bot is not linked", () => {
  render(<QrPanel initialBot={unlinkedBot} apiBaseUrl="http://api" pollIntervalMs={10000} />);
  expect(screen.getByRole("img", { name: /qr/i })).toBeInTheDocument();
  expect(screen.queryByText(/отключить/i)).not.toBeInTheDocument();
});

it("switches to the connected view once polling finds linked_at set", async () => {
  vi.mocked(api.fetchBot).mockResolvedValue(linkedBot);
  render(<QrPanel initialBot={unlinkedBot} apiBaseUrl="http://api" pollIntervalMs={20} />);

  await waitFor(() => {
    expect(screen.getByText(/996700000000/)).toBeInTheDocument();
  });
  expect(screen.queryByRole("img", { name: /qr/i })).not.toBeInTheDocument();
});

it("logs out and returns to the QR view", async () => {
  vi.mocked(api.fetchBot).mockResolvedValue(unlinkedBot);
  vi.mocked(api.logoutBot).mockResolvedValue(undefined);
  render(<QrPanel initialBot={linkedBot} apiBaseUrl="http://api" pollIntervalMs={10000} />);

  fireEvent.click(screen.getByRole("button", { name: /отключить/i }));

  await waitFor(() => {
    expect(api.logoutBot).toHaveBeenCalledWith("http://api", "1");
  });
  await waitFor(() => {
    expect(screen.getByRole("img", { name: /qr/i })).toBeInTheDocument();
  });
});
