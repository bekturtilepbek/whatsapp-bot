import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BotSettingsForm } from "@/components/BotSettingsForm";
import * as api from "@/lib/api";
import type { Bot, BotSettings } from "@/lib/api";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    patchBotSettings: vi.fn(),
  };
});

const initialSettings: Required<BotSettings> = {
  batch_timeout_seconds: 1,
  auto_release_minutes: 12,
  reminder_enabled: false,
  reminder_delay_minutes: 60,
  reminder_message: "стандартный текст",
  media_fallback_text: "заглушка",
  media_max_size_bytes: 16 * 1024 * 1024,
};

afterEach(() => {
  vi.clearAllMocks();
});

it("renders current settings", () => {
  render(<BotSettingsForm botId="1" apiBaseUrl="http://api" initialSettings={initialSettings} />);
  expect(screen.getByLabelText(/таймаут батчинга/i)).toHaveValue(1);
  expect(screen.getByLabelText(/авто-возврат/i)).toHaveValue(12);
  expect(screen.getByLabelText(/включены/i)).not.toBeChecked();
  expect(screen.getByLabelText(/задержка/i)).toHaveValue(60);
  expect(screen.getByLabelText(/текст напоминания/i)).toHaveValue("стандартный текст");
  expect(screen.getByLabelText(/заглушка на неподдерживаемое медиа/i)).toHaveValue("заглушка");
  expect(screen.getByLabelText(/макс\. размер/i)).toHaveValue(16);
});

it("saves edited settings with the full current settings object", async () => {
  vi.mocked(api.patchBotSettings).mockResolvedValue({} as Bot);
  render(<BotSettingsForm botId="1" apiBaseUrl="http://api" initialSettings={initialSettings} />);

  fireEvent.change(screen.getByLabelText(/таймаут батчинга/i), { target: { value: "2.5" } });
  fireEvent.click(screen.getByLabelText(/включены/i));
  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));

  await waitFor(() => {
    expect(api.patchBotSettings).toHaveBeenCalledWith("http://api", "1", {
      ...initialSettings,
      batch_timeout_seconds: 2.5,
      reminder_enabled: true,
    });
  });
  expect(await screen.findByRole("status")).toHaveTextContent(/сохранено/i);
});

it("converts the MB input back to bytes on save", async () => {
  vi.mocked(api.patchBotSettings).mockResolvedValue({} as Bot);
  render(<BotSettingsForm botId="1" apiBaseUrl="http://api" initialSettings={initialSettings} />);

  fireEvent.change(screen.getByLabelText(/макс\. размер/i), { target: { value: "8" } });
  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));

  await waitFor(() => {
    expect(api.patchBotSettings).toHaveBeenCalledWith("http://api", "1", {
      ...initialSettings,
      media_max_size_bytes: 8 * 1024 * 1024,
    });
  });
});

it("shows an error when saving fails", async () => {
  vi.mocked(api.patchBotSettings).mockRejectedValue(new Error("save failed"));
  render(<BotSettingsForm botId="1" apiBaseUrl="http://api" initialSettings={initialSettings} />);

  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent(/save failed/i);
  });
});
