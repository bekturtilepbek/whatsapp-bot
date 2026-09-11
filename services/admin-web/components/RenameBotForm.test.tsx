import { afterEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { RenameBotForm } from "@/components/RenameBotForm";
import * as api from "@/lib/api";
import type { Bot } from "@/lib/api";

const refreshMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: refreshMock }),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    patchBotName: vi.fn(),
  };
});

const renamedBot: Bot = {
  id: "b1",
  name: "Новое имя",
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

it("shows the current name by default", () => {
  render(<RenameBotForm botId="b1" apiBaseUrl="http://api" initialName="Старое имя" />);
  expect(screen.getByLabelText("Название бота")).toHaveValue("Старое имя");
});

it("saves the new name and refreshes", async () => {
  vi.mocked(api.patchBotName).mockResolvedValue(renamedBot);
  render(<RenameBotForm botId="b1" apiBaseUrl="http://api" initialName="Старое имя" />);

  fireEvent.change(screen.getByLabelText("Название бота"), { target: { value: "Новое имя" } });
  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));

  await waitFor(() => {
    expect(api.patchBotName).toHaveBeenCalledWith("http://api", "b1", "Новое имя");
  });
  expect(refreshMock).toHaveBeenCalled();
});

it("does not save when the name is blank", async () => {
  render(<RenameBotForm botId="b1" apiBaseUrl="http://api" initialName="Старое имя" />);

  fireEvent.change(screen.getByLabelText("Название бота"), { target: { value: "   " } });
  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent(/не может быть пустым/i);
  });
  expect(api.patchBotName).not.toHaveBeenCalled();
});

it("shows an error and does not refresh when saving fails", async () => {
  vi.mocked(api.patchBotName).mockRejectedValue(new Error("save failed"));
  render(<RenameBotForm botId="b1" apiBaseUrl="http://api" initialName="Старое имя" />);

  fireEvent.change(screen.getByLabelText("Название бота"), { target: { value: "Новое имя" } });
  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent(/save failed/i);
  });
  expect(refreshMock).not.toHaveBeenCalled();
});
