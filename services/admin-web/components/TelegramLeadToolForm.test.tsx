import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@/lib/test-utils";
import { TelegramLeadToolForm } from "@/components/TelegramLeadToolForm";
import * as api from "@/lib/api";
import type { ToolBinding } from "@/lib/api";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    saveBotTool: vi.fn(),
    deleteBotTool: vi.fn(),
  };
});

afterEach(() => {
  vi.clearAllMocks();
});

it("renders disabled with empty fields when no binding exists yet", () => {
  render(
    <TelegramLeadToolForm botId="1" apiBaseUrl="http://api" initialBinding={null} />,
  );
  expect(screen.getByLabelText(/отправлять заявки/i)).not.toBeChecked();
  expect(screen.getByLabelText(/id группы/i)).toHaveValue("");
  expect(screen.getByLabelText(/id группы/i)).toBeDisabled();
});

it("renders enabled with the saved chat_id and template", () => {
  const binding: ToolBinding = {
    tool_name: "send_telegram_lead",
    config: { chat_id: "-1001234567890", message_template: "Заявка: {client_name}" },
  };
  render(
    <TelegramLeadToolForm botId="1" apiBaseUrl="http://api" initialBinding={binding} />,
  );
  expect(screen.getByLabelText(/отправлять заявки/i)).toBeChecked();
  expect(screen.getByLabelText(/id группы/i)).toHaveValue("-1001234567890");
  expect(screen.getByLabelText(/текст сообщения/i)).toHaveValue("Заявка: {client_name}");
});

it("saves chat_id and template when enabled", async () => {
  vi.mocked(api.saveBotTool).mockResolvedValue({} as ToolBinding);
  render(
    <TelegramLeadToolForm botId="1" apiBaseUrl="http://api" initialBinding={null} />,
  );

  fireEvent.click(screen.getByLabelText(/отправлять заявки/i));
  fireEvent.change(screen.getByLabelText(/id группы/i), { target: { value: "-100999" } });
  fireEvent.change(screen.getByLabelText(/текст сообщения/i), {
    target: { value: "Заявка: {client_name}" },
  });
  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));

  await waitFor(() => {
    expect(api.saveBotTool).toHaveBeenCalledWith("http://api", "1", "send_telegram_lead", {
      chat_id: "-100999",
      message_template: "Заявка: {client_name}",
    });
  });
});

it("deletes the binding when disabled and saved", async () => {
  vi.mocked(api.deleteBotTool).mockResolvedValue(undefined);
  const binding: ToolBinding = {
    tool_name: "send_telegram_lead",
    config: { chat_id: "-100999", message_template: "" },
  };
  render(
    <TelegramLeadToolForm botId="1" apiBaseUrl="http://api" initialBinding={binding} />,
  );

  fireEvent.click(screen.getByLabelText(/отправлять заявки/i));
  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));

  await waitFor(() => {
    expect(api.deleteBotTool).toHaveBeenCalledWith("http://api", "1", "send_telegram_lead");
  });
  expect(api.saveBotTool).not.toHaveBeenCalled();
});

it("blocks saving when enabled without a chat_id", async () => {
  render(
    <TelegramLeadToolForm botId="1" apiBaseUrl="http://api" initialBinding={null} />,
  );

  fireEvent.click(screen.getByLabelText(/отправлять заявки/i));
  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));

  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(api.saveBotTool).not.toHaveBeenCalled();
  expect(screen.getByLabelText(/id группы/i)).toHaveAttribute("aria-invalid", "true");
  // getByText здесь неоднозначен — тот же текст есть в тосте с ошибкой;
  // подпись поля находим через сам инпут, а не текст.
  expect(screen.getByLabelText(/id группы/i).closest("label")).toHaveClass("text-danger");
  const shakeWrapper = document.querySelector(".animate-shake");
  expect(shakeWrapper).toContainElement(screen.getByLabelText(/id группы/i));
});

it("shows an error toast when saving fails", async () => {
  vi.mocked(api.saveBotTool).mockRejectedValue(new Error("save failed"));
  render(
    <TelegramLeadToolForm botId="1" apiBaseUrl="http://api" initialBinding={null} />,
  );

  fireEvent.click(screen.getByLabelText(/отправлять заявки/i));
  fireEvent.change(screen.getByLabelText(/id группы/i), { target: { value: "-100999" } });
  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent(/save failed/i);
  });
});
