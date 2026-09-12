import { afterEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@/lib/test-utils";
import { SandboxChat } from "@/components/SandboxChat";
import * as api from "@/lib/api";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    sendSandboxMessage: vi.fn(),
  };
});

afterEach(() => {
  vi.clearAllMocks();
});

function sendMessage(text: string) {
  fireEvent.change(screen.getByLabelText("Сообщение клиента"), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: /отправить/i }));
}

it("shows a placeholder before the first message", () => {
  render(<SandboxChat apiBaseUrl="http://api" botId="b1" />);
  expect(
    screen.getByText("Отправьте сообщение, чтобы проверить, как отвечает бот")
  ).toBeInTheDocument();
});

it("sends the message and renders the reply with token usage", async () => {
  vi.mocked(api.sendSandboxMessage).mockResolvedValue({
    reply: "Здравствуйте!",
    tokens_in: 11,
    tokens_out: 7,
    model: "gpt-4o-mini",
  });
  render(<SandboxChat apiBaseUrl="http://api" botId="b1" />);

  sendMessage("Привет");

  expect(screen.getByText(/привет/i)).toBeInTheDocument();
  await waitFor(() => {
    expect(screen.getByText("Здравствуйте!")).toBeInTheDocument();
  });
  expect(screen.getByText(/gpt-4o-mini.*11\+7 токенов/)).toBeInTheDocument();
  expect(api.sendSandboxMessage).toHaveBeenCalledWith("http://api", "b1", [], "Привет");
});

it("sends prior turns as history on the second message", async () => {
  vi.mocked(api.sendSandboxMessage).mockResolvedValueOnce({
    reply: "Здравствуйте!",
    tokens_in: 1,
    tokens_out: 1,
    model: "gpt-4o-mini",
  });
  render(<SandboxChat apiBaseUrl="http://api" botId="b1" />);

  sendMessage("Привет");
  await waitFor(() => expect(screen.getByText("Здравствуйте!")).toBeInTheDocument());

  vi.mocked(api.sendSandboxMessage).mockResolvedValueOnce({
    reply: "Кроссовки за 5000",
    tokens_in: 2,
    tokens_out: 2,
    model: "gpt-4o-mini",
  });
  sendMessage("Что у вас есть?");

  await waitFor(() => {
    expect(api.sendSandboxMessage).toHaveBeenLastCalledWith(
      "http://api",
      "b1",
      [
        { role: "user", content: "Привет" },
        { role: "assistant", content: "Здравствуйте!" },
      ],
      "Что у вас есть?"
    );
  });
});

it("does not send an empty or whitespace-only message", () => {
  render(<SandboxChat apiBaseUrl="http://api" botId="b1" />);
  sendMessage("   ");
  expect(api.sendSandboxMessage).not.toHaveBeenCalled();
});

it("shows an error toast and drops the optimistic bubble on failure", async () => {
  vi.mocked(api.sendSandboxMessage).mockRejectedValue(new Error("boom"));
  render(<SandboxChat apiBaseUrl="http://api" botId="b1" />);

  sendMessage("Привет");
  expect(screen.getByText(/привет/i)).toBeInTheDocument();

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent("boom");
  });
  expect(screen.queryByText(/привет/i)).not.toBeInTheDocument();
});
