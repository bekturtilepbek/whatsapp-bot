import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@/lib/test-utils";
import { SandboxChat } from "@/components/SandboxChat";
import * as api from "@/lib/api";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    sendSandboxMessage: vi.fn(),
    sendSandboxMediaMessage: vi.fn(),
  };
});

beforeEach(() => {
  // jsdom не реализует URL.createObjectURL/revokeObjectURL — нужны для
  // локального превью прикреплённой картинки до отправки.
  URL.createObjectURL = vi.fn(() => "blob:mock-preview-url");
  URL.revokeObjectURL = vi.fn();
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
    media: [],
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

  resolveReply({
    reply: "Здравствуйте!",
    tokens_in: 1,
    tokens_out: 1,
    model: "gpt-4o-mini",
    media: [],
  });
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
    media: [],
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
    media: [],
  });
  renderChat();

  sendMessage("Привет");
  await waitFor(() => expect(screen.getByText("Здравствуйте!")).toBeInTheDocument());

  vi.mocked(api.sendSandboxMessage).mockResolvedValueOnce({
    reply: "Кроссовки за 5000",
    tokens_in: 2,
    tokens_out: 2,
    model: "gpt-4o-mini",
    media: [],
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

it("renders image media from a tool call inline in the bot bubble", async () => {
  vi.mocked(api.sendSandboxMessage).mockResolvedValue({
    reply: "*Кроссовки*\nЦена: 5000",
    tokens_in: 5,
    tokens_out: 5,
    model: "gpt-4o-mini",
    media: [
      { storage_key: "bots/b1/products/img-1.jpg", mime_type: "image/jpeg", filename: null },
    ],
  });
  renderChat();

  sendMessage("Есть кроссовки?");

  await waitFor(() => {
    const image = screen.getByRole("img", { name: /кроссовки/i });
    expect(image).toHaveAttribute(
      "src",
      "http://api/bots/b1/sandbox/media?key=bots%2Fb1%2Fproducts%2Fimg-1.jpg&mime_type=image%2Fjpeg",
    );
  });
});

it("renders video media from a tool call as an inline player, not a link", async () => {
  vi.mocked(api.sendSandboxMessage).mockResolvedValue({
    reply: "*Товар*\nВидео обзор",
    tokens_in: 5,
    tokens_out: 5,
    model: "gpt-4o-mini",
    media: [
      { storage_key: "bots/b1/products/tour.mp4", mime_type: "video/mp4", filename: null },
    ],
  });
  renderChat();

  sendMessage("Есть видео товара?");

  await waitFor(() => {
    const video = document.querySelector("video.sbx-bubble-media-video");
    expect(video).not.toBeNull();
    expect(video).toHaveAttribute(
      "src",
      "http://api/bots/b1/sandbox/media?key=bots%2Fb1%2Fproducts%2Ftour.mp4&mime_type=video%2Fmp4",
    );
  });
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
});

it("renders non-image media as a download link with the filename", async () => {
  vi.mocked(api.sendSandboxMessage).mockResolvedValue({
    reply: "Отправляю файл price-list.pdf.",
    tokens_in: 5,
    tokens_out: 5,
    model: "gpt-4o-mini",
    media: [
      {
        storage_key: "bots/b1/documents/price-list.pdf",
        mime_type: "application/pdf",
        filename: "price-list.pdf",
      },
    ],
  });
  renderChat();

  sendMessage("Пришли прайс");

  await waitFor(() => {
    const link = screen.getByRole("link", { name: /price-list\.pdf/ });
    expect(link).toHaveAttribute(
      "href",
      "http://api/bots/b1/sandbox/media?key=bots%2Fb1%2Fdocuments%2Fprice-list.pdf&mime_type=application%2Fpdf",
    );
  });
});

function attachFile(file: File) {
  const input = screen.getByLabelText("Прикрепить файл") as HTMLInputElement;
  fireEvent.change(input, { target: { files: [file] } });
}

it("has an accessible attach-file input", () => {
  renderChat();
  expect(screen.getByLabelText("Прикрепить файл")).toBeInTheDocument();
});

it("focuses the message input on mount so typing can start immediately", () => {
  renderChat();
  expect(screen.getByLabelText("Сообщение клиента")).toHaveFocus();
});

it("returns focus to the message input after attaching a file", () => {
  renderChat();
  attachFile(new File(["x"], "photo.jpg", { type: "image/jpeg" }));

  expect(screen.getByLabelText("Сообщение клиента")).toHaveFocus();
});

it("shows an image preview after attaching a photo and enables sending without typed text", () => {
  renderChat();
  const file = new File(["x"], "photo.jpg", { type: "image/jpeg" });

  attachFile(file);

  expect(screen.getByAltText("photo.jpg")).toHaveAttribute("src", "blob:mock-preview-url");
  expect(screen.getByRole("button", { name: /отправить/i })).not.toBeDisabled();
});

it("shows a filename chip (no image preview) after attaching a PDF", () => {
  renderChat();
  const file = new File(["x"], "price.pdf", { type: "application/pdf" });

  attachFile(file);

  expect(screen.getByText("📎 price.pdf")).toBeInTheDocument();
  expect(screen.queryByRole("img", { name: "price.pdf" })).not.toBeInTheDocument();
});

it("removing the attachment before sending clears the preview", () => {
  renderChat();
  attachFile(new File(["x"], "photo.jpg", { type: "image/jpeg" }));

  fireEvent.click(screen.getByRole("button", { name: "Убрать вложение" }));

  expect(screen.queryByAltText("photo.jpg")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /отправить/i })).toBeDisabled();
});

it("sends an attached image with a caption via sendSandboxMediaMessage", async () => {
  vi.mocked(api.sendSandboxMediaMessage).mockResolvedValue({
    reply: "Это кроссовки.",
    tokens_in: 10,
    tokens_out: 5,
    model: "gpt-4o-mini",
    media: [],
  });
  renderChat();
  const file = new File(["x"], "photo.jpg", { type: "image/jpeg" });
  attachFile(file);
  fireEvent.change(screen.getByLabelText("Сообщение клиента"), {
    target: { value: "Что это?" },
  });

  fireEvent.click(screen.getByRole("button", { name: /отправить/i }));

  expect(screen.getByText("Что это?")).toBeInTheDocument();
  await waitFor(() => {
    expect(screen.getByText("Это кроссовки.")).toBeInTheDocument();
  });
  expect(api.sendSandboxMediaMessage).toHaveBeenCalledWith(
    "http://api",
    "b1",
    [],
    file,
    "Что это?",
  );
  // Рабочее вложение и подпись очищены после отправки — форма готова к
  // следующему ходу (сама картинка остаётся видна в уже отправленном пузыре).
  expect(screen.queryByRole("button", { name: "Убрать вложение" })).not.toBeInTheDocument();
  expect(screen.getByLabelText("Сообщение клиента")).toHaveValue("");
});

it("sends an attached image without a caption using a placeholder bubble", async () => {
  vi.mocked(api.sendSandboxMediaMessage).mockResolvedValue({
    reply: "Вижу кроссовки.",
    tokens_in: 10,
    tokens_out: 5,
    model: "gpt-4o-mini",
    media: [],
  });
  renderChat();
  attachFile(new File(["x"], "photo.jpg", { type: "image/jpeg" }));

  fireEvent.click(screen.getByRole("button", { name: /отправить/i }));

  expect(screen.getByText("[фото]")).toBeInTheDocument();
  await waitFor(() => {
    expect(screen.getByText("Вижу кроссовки.")).toBeInTheDocument();
  });
  expect(api.sendSandboxMediaMessage).toHaveBeenCalledWith(
    "http://api",
    "b1",
    [],
    expect.any(File),
    undefined,
  );
});

it("sends an attached PDF with a placeholder bubble for documents", async () => {
  vi.mocked(api.sendSandboxMediaMessage).mockResolvedValue({
    reply: "В документе цены.",
    tokens_in: 10,
    tokens_out: 5,
    model: "gpt-4o-mini",
    media: [],
  });
  renderChat();
  attachFile(new File(["x"], "price.pdf", { type: "application/pdf" }));

  fireEvent.click(screen.getByRole("button", { name: /отправить/i }));

  expect(screen.getByText("[документ]")).toBeInTheDocument();
  await waitFor(() => {
    expect(screen.getByText("В документе цены.")).toBeInTheDocument();
  });
});

it("shows an error toast and keeps the form usable when a media message fails", async () => {
  vi.mocked(api.sendSandboxMediaMessage).mockRejectedValue(new Error("boom"));
  renderChat();
  attachFile(new File(["x"], "photo.jpg", { type: "image/jpeg" }));

  fireEvent.click(screen.getByRole("button", { name: /отправить/i }));

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent("boom");
  });
  expect(screen.queryByText("[фото]")).not.toBeInTheDocument();
});
