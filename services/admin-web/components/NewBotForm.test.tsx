import { afterEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@/lib/test-utils";
import { NewBotForm } from "@/components/NewBotForm";
import * as api from "@/lib/api";
import type { Bot } from "@/lib/api";

const pushMock = vi.fn();
const refreshMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, refresh: refreshMock }),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    createBot: vi.fn(),
  };
});

const createdBot: Bot = {
  id: "b1",
  name: "Новый бот",
  enabled: true,
  phone: null,
  linked_at: null,
  system_prompt: "",
  image_prompt: null,
  pdf_prompt: null,
};

afterEach(() => {
  vi.clearAllMocks();
});

it("does nothing when the name is empty", async () => {
  render(<NewBotForm apiBaseUrl="http://api" />);
  fireEvent.click(screen.getByRole("button", { name: /создать/i }));
  await waitFor(() => {
    expect(api.createBot).not.toHaveBeenCalled();
  });
});

it("creates a bot and navigates to its page", async () => {
  vi.mocked(api.createBot).mockResolvedValue(createdBot);
  render(<NewBotForm apiBaseUrl="http://api" />);

  fireEvent.change(screen.getByLabelText("Имя"), { target: { value: "Новый бот" } });
  fireEvent.click(screen.getByRole("button", { name: /создать/i }));

  await waitFor(() => {
    expect(api.createBot).toHaveBeenCalledWith("http://api", "Новый бот");
  });
  await waitFor(() => {
    expect(pushMock).toHaveBeenCalledWith("/bots/b1");
  });
  expect(refreshMock).toHaveBeenCalled();
  expect(screen.getByRole("status")).toHaveTextContent(/бот создан/i);
});

it("shows an error and does not navigate when creation fails", async () => {
  vi.mocked(api.createBot).mockRejectedValue(new Error("create failed"));
  render(<NewBotForm apiBaseUrl="http://api" />);

  fireEvent.change(screen.getByLabelText("Имя"), { target: { value: "Сломанный бот" } });
  fireEvent.click(screen.getByRole("button", { name: /создать/i }));

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent(/create failed/i);
  });
  expect(pushMock).not.toHaveBeenCalled();
});
