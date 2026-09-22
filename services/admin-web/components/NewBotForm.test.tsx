import { afterEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@/lib/test-utils";
import { NewBotForm } from "@/components/NewBotForm";
import * as api from "@/lib/api";
import type { Bot, PrompterBrief } from "@/lib/api";

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

const prompters: PrompterBrief[] = [
  { id: "p1", email: "prompter1@example.com" },
  { id: "p2", email: "prompter2@example.com" },
];

it("shows an error and does not call the api when the name is empty", async () => {
  render(<NewBotForm apiBaseUrl="http://api" prompters={[]} />);
  fireEvent.click(screen.getByRole("button", { name: /создать/i }));

  expect(await screen.findByRole("alert")).toHaveTextContent(/введите имя бота/i);
  expect(api.createBot).not.toHaveBeenCalled();
  expect(screen.getByLabelText("Имя")).toHaveAttribute("aria-invalid", "true");
  expect(screen.getByText("Имя").closest("label")).toHaveClass("text-danger");
  const shakeWrapper = document.querySelector(".animate-shake");
  expect(shakeWrapper).toContainElement(screen.getByText("Имя"));
  expect(shakeWrapper).toContainElement(screen.getByLabelText("Имя"));
});

it("creates a bot with no responsible user selected (null) and navigates to its page", async () => {
  vi.mocked(api.createBot).mockResolvedValue(createdBot);
  render(<NewBotForm apiBaseUrl="http://api" prompters={[]} />);

  fireEvent.change(screen.getByLabelText("Имя"), { target: { value: "Новый бот" } });
  fireEvent.click(screen.getByRole("button", { name: /создать/i }));

  await waitFor(() => {
    expect(api.createBot).toHaveBeenCalledWith("http://api", "Новый бот", null);
  });
  await waitFor(() => {
    expect(pushMock).toHaveBeenCalledWith("/bots/b1");
  });
  expect(refreshMock).toHaveBeenCalled();
  expect(screen.getByRole("status")).toHaveTextContent(/бот создан/i);
});

it("hides the responsible-user section when there are no prompters", () => {
  render(<NewBotForm apiBaseUrl="http://api" prompters={[]} />);
  expect(screen.queryByText(/ответственный/i)).not.toBeInTheDocument();
});

it("passes the selected prompter as the responsible user", async () => {
  vi.mocked(api.createBot).mockResolvedValue(createdBot);
  render(<NewBotForm apiBaseUrl="http://api" prompters={prompters} />);

  fireEvent.change(screen.getByLabelText("Имя"), { target: { value: "Новый бот" } });
  fireEvent.change(screen.getByLabelText(/ответственный/i), { target: { value: "p2" } });
  fireEvent.click(screen.getByRole("button", { name: /создать/i }));

  await waitFor(() => {
    expect(api.createBot).toHaveBeenCalledWith("http://api", "Новый бот", "p2");
  });
});

it("shows an error and does not navigate when creation fails", async () => {
  vi.mocked(api.createBot).mockRejectedValue(new Error("create failed"));
  render(<NewBotForm apiBaseUrl="http://api" prompters={[]} />);

  fireEvent.change(screen.getByLabelText("Имя"), { target: { value: "Сломанный бот" } });
  fireEvent.click(screen.getByRole("button", { name: /создать/i }));

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent(/create failed/i);
  });
  expect(pushMock).not.toHaveBeenCalled();
});
