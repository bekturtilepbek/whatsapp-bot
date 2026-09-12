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

function renderChat() {
  return render(<SandboxChat apiBaseUrl="http://api" botId="b1" botName="Тестовый бот" />);
}

function sendMessage(text: string) {
  fireEvent.change(screen.getByLabelText("Сообщение клиента"), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: /отправить/i }));
}

it("shows the bot name in the chat header", () => {
  renderChat();
  expect(screen.getByText("Тестовый бот")).toBeInTheDocument();
});

it("shows a placeholder before the first message", () => {
  renderChat();
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
  renderChat();

  sendMessage("Привет");

  expect(screen.getByText("Привет")).toBeInTheDocument();
  await waitFor(() => {
    expect(screen.getByText("Здравствуйте!")).toBeInTheDocument();
  });
  expect(screen.getByText(/gpt-4o-mini.*11\+7 токенов/)).toBeInTheDocument();
  expect(api.sendSandboxMessage).toHaveBeenCalledWith("http://api", "b1", [], "Привет");
});

it("shows a typing indicator while waiting for the reply", async () => {
  let resolveReply: (v: api.SandboxMessageResult) => void = () => {};
  vi.mocked(api.sendSandboxMessage).mockReturnValue(
    new Promise((resolve) => {
      resolveReply = resolve;
    })
  );
  renderChat();

  sendMessage("Привет");
  expect(screen.getByLabelText("Бот печатает")).toBeInTheDocument();
  expect(screen.getByText("печатает…")).toBeInTheDocument();

  resolveReply({ reply: "Здравствуйте!", tokens_in: 1, tokens_out: 1, model: "gpt-4o-mini" });
  await waitFor(() => {
    expect(screen.queryByLabelText("Бот печатает")).not.toBeInTheDocument();
  });
});

it("sends on Enter and inserts a newline on Shift+Enter instead", async () => {
  vi.mocked(api.sendSandboxMessage).mockResolvedValue({
    reply: "ok",
    tokens_in: 1,
    tokens_out: 1,
    model: "gpt-4o-mini",
  });
  renderChat();
  const textarea = screen.getByLabelText("Сообщение клиента");

  fireEvent.change(textarea, { target: { value: "строка 1" } });
  fireEvent.keyDown(textarea, { key: "Enter", shiftKey: true });
  expect(api.sendSandboxMessage).not.toHaveBeenCalled();

  fireEvent.change(textarea, { target: { value: "строка 1\nстрока 2" } });
  fireEvent.keyDown(textarea, { key: "Enter", shiftKey: false });
  await waitFor(() => {
    expect(api.sendSandboxMessage).toHaveBeenCalledWith(
      "http://api",
      "b1",
      [],
      "строка 1\nстрока 2"
    );
  });
});

it("sends prior turns as history on the second message", async () => {
  vi.mocked(api.sendSandboxMessage).mockResolvedValueOnce({
    reply: "Здравствуйте!",
    tokens_in: 1,
    tokens_out: 1,
    model: "gpt-4o-mini",
  });
  renderChat();

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
  renderChat();
  sendMessage("   ");
  expect(api.sendSandboxMessage).not.toHaveBeenCalled();
});

it("shows an error toast and drops the optimistic bubble on failure", async () => {
  vi.mocked(api.sendSandboxMessage).mockRejectedValue(new Error("boom"));
  renderChat();

  sendMessage("Привет");
  expect(screen.getByText("Привет")).toBeInTheDocument();

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent("boom");
  });
  expect(screen.queryByText("Привет")).not.toBeInTheDocument();
});
