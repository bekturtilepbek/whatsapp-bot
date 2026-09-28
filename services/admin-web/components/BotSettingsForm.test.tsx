import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@/lib/test-utils";
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
  media_reaction_enabled: true,
  media_reaction_emoji: "👍",
  model: "gpt-4o-mini",
  product_display: { show_name: true, show_description: true, show_price: true },
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
  expect(screen.getByLabelText(/реагировать эмодзи/i)).toBeChecked();
  expect(screen.getByLabelText(/эмодзи реакции/i)).toHaveValue("👍");
  expect(screen.getByLabelText(/модель llm/i)).toHaveValue("gpt-4o-mini");
  expect(screen.getByLabelText(/показывать название/i)).toBeChecked();
  expect(screen.getByLabelText(/показывать описание/i)).toBeChecked();
  expect(screen.getByLabelText(/показывать цену/i)).toBeChecked();
  // Нет общей кнопки "Сохранить" — переделка 2026-09-28, каждое поле
  // сохраняется само (по запросу пользователя).
  expect(screen.queryByRole("button", { name: /сохранить/i })).not.toBeInTheDocument();
});

it("saves a switch immediately on change, without waiting for blur elsewhere", async () => {
  vi.mocked(api.patchBotSettings).mockResolvedValue({} as Bot);
  render(<BotSettingsForm botId="1" apiBaseUrl="http://api" initialSettings={initialSettings} />);

  fireEvent.click(screen.getByLabelText(/включены/i));

  await waitFor(() => {
    expect(api.patchBotSettings).toHaveBeenCalledWith("http://api", "1", { reminder_enabled: true });
  });
  expect(await screen.findByRole("status")).toHaveTextContent(/сохранено/i);
});

it("saves a number field on blur, not on every keystroke", async () => {
  vi.mocked(api.patchBotSettings).mockResolvedValue({} as Bot);
  render(<BotSettingsForm botId="1" apiBaseUrl="http://api" initialSettings={initialSettings} />);

  const field = screen.getByLabelText(/таймаут батчинга/i);
  fireEvent.change(field, { target: { value: "2.5" } });
  expect(api.patchBotSettings).not.toHaveBeenCalled(); // ещё не blur

  fireEvent.blur(field);
  await waitFor(() => {
    expect(api.patchBotSettings).toHaveBeenCalledWith("http://api", "1", {
      batch_timeout_seconds: 2.5,
    });
  });
});

it("does not call the API on blur when the value did not actually change", async () => {
  vi.mocked(api.patchBotSettings).mockResolvedValue({} as Bot);
  render(<BotSettingsForm botId="1" apiBaseUrl="http://api" initialSettings={initialSettings} />);

  const field = screen.getByLabelText(/таймаут батчинга/i);
  fireEvent.focus(field);
  fireEvent.blur(field);

  expect(api.patchBotSettings).not.toHaveBeenCalled();
});

it("converts the MB input back to bytes on save", async () => {
  vi.mocked(api.patchBotSettings).mockResolvedValue({} as Bot);
  render(<BotSettingsForm botId="1" apiBaseUrl="http://api" initialSettings={initialSettings} />);

  const field = screen.getByLabelText(/макс\. размер/i);
  fireEvent.change(field, { target: { value: "8" } });
  fireEvent.blur(field);

  await waitFor(() => {
    expect(api.patchBotSettings).toHaveBeenCalledWith("http://api", "1", {
      media_max_size_bytes: 8 * 1024 * 1024,
    });
  });
});

it("keeps the typed MB value as typed, without a float tail from the bytes round-trip", async () => {
  vi.mocked(api.patchBotSettings).mockResolvedValue({} as Bot);
  render(<BotSettingsForm botId="1" apiBaseUrl="http://api" initialSettings={initialSettings} />);

  const field = screen.getByLabelText(/макс\. размер/i);
  fireEvent.change(field, { target: { value: "16.1" } });
  // Раньше поле перерисовывалось из байтов: 16.1 МБ -> 16882074 Б -> 16.1000003814...
  expect(field).toHaveValue(16.1);
  fireEvent.blur(field);

  await waitFor(() => {
    expect(api.patchBotSettings).toHaveBeenCalledWith("http://api", "1", {
      media_max_size_bytes: Math.round(16.1 * 1024 * 1024),
    });
  });
  expect(field).toHaveValue(16.1);
});

it("saves media reaction fields independently (FEATURES.md 9.10)", async () => {
  vi.mocked(api.patchBotSettings).mockResolvedValue({} as Bot);
  render(<BotSettingsForm botId="1" apiBaseUrl="http://api" initialSettings={initialSettings} />);

  fireEvent.click(screen.getByLabelText(/реагировать эмодзи/i));
  await waitFor(() => {
    expect(api.patchBotSettings).toHaveBeenCalledWith("http://api", "1", {
      media_reaction_enabled: false,
    });
  });

  const emojiField = screen.getByLabelText(/эмодзи реакции/i);
  fireEvent.change(emojiField, { target: { value: "🎉" } });
  fireEvent.blur(emojiField);
  await waitFor(() => {
    expect(api.patchBotSettings).toHaveBeenCalledWith("http://api", "1", {
      media_reaction_emoji: "🎉",
    });
  });
});

it("saves a changed model immediately (Волна 4)", async () => {
  vi.mocked(api.patchBotSettings).mockResolvedValue({} as Bot);
  render(<BotSettingsForm botId="1" apiBaseUrl="http://api" initialSettings={initialSettings} />);

  fireEvent.change(screen.getByLabelText(/модель llm/i), { target: { value: "gpt-4o" } });

  await waitFor(() => {
    expect(api.patchBotSettings).toHaveBeenCalledWith("http://api", "1", { model: "gpt-4o" });
  });
});

it("saves the whole product_display object when any of its switches changed (FEATURES.md 4.5)", async () => {
  vi.mocked(api.patchBotSettings).mockResolvedValue({} as Bot);
  render(<BotSettingsForm botId="1" apiBaseUrl="http://api" initialSettings={initialSettings} />);

  fireEvent.click(screen.getByLabelText(/показывать цену/i));

  await waitFor(() => {
    expect(api.patchBotSettings).toHaveBeenCalledWith("http://api", "1", {
      product_display: { show_name: true, show_description: true, show_price: false },
    });
  });
});

it("shows an error and reverts the switch when saving fails", async () => {
  vi.mocked(api.patchBotSettings).mockRejectedValue(new Error("save failed"));
  render(<BotSettingsForm botId="1" apiBaseUrl="http://api" initialSettings={initialSettings} />);

  const toggle = screen.getByLabelText(/включены/i);
  fireEvent.click(toggle);

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent(/save failed/i);
  });
  // Откат к последнему подтверждённому состоянию — сбой не должен молча
  // оставить UI в несинхронизированном с бэкендом состоянии.
  expect(toggle).not.toBeChecked();
});

it("shows an error and reverts a number field to baseline when saving fails", async () => {
  vi.mocked(api.patchBotSettings).mockRejectedValue(new Error("save failed"));
  render(<BotSettingsForm botId="1" apiBaseUrl="http://api" initialSettings={initialSettings} />);

  const field = screen.getByLabelText(/таймаут батчинга/i);
  fireEvent.change(field, { target: { value: "2.5" } });
  fireEvent.blur(field);

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent(/save failed/i);
  });
  expect(field).toHaveValue(1);
});

describe("validation blocks the save call, shows an error, and reverts the field", () => {
  it("rejects a negative batch timeout", async () => {
    render(<BotSettingsForm botId="1" apiBaseUrl="http://api" initialSettings={initialSettings} />);
    const field = screen.getByLabelText(/таймаут батчинга/i);
    fireEvent.change(field, { target: { value: "-5" } });
    fireEvent.blur(field);

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(api.patchBotSettings).not.toHaveBeenCalled();
    expect(field).toHaveValue(1);
  });

  // Пустое поле раньше превращалось в 0 (Number("") === 0) и молча
  // сохранялось: авто-возврат 0 ломал handoff в worker (SET EX 0), задержка
  // напоминания 0 слала напоминание сразу после ответа бота.
  it.each([
    [/таймаут батчинга/i, 1],
    [/авто-возврат/i, 12],
    [/задержка/i, 60],
  ])("rejects an emptied number field %s instead of saving 0", async (label, original) => {
    render(<BotSettingsForm botId="1" apiBaseUrl="http://api" initialSettings={initialSettings} />);
    const field = screen.getByLabelText(label);
    fireEvent.change(field, { target: { value: "" } });
    fireEvent.blur(field);

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(api.patchBotSettings).not.toHaveBeenCalled();
    expect(field).toHaveValue(original);
  });

  it.each([[/авто-возврат/i], [/задержка/i]])("rejects 0 minutes for %s", async (label) => {
    render(<BotSettingsForm botId="1" apiBaseUrl="http://api" initialSettings={initialSettings} />);
    const field = screen.getByLabelText(label);
    fireEvent.change(field, { target: { value: "0" } });
    fireEvent.blur(field);

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(api.patchBotSettings).not.toHaveBeenCalled();
  });

  it("rejects an emptied media size field", async () => {
    render(<BotSettingsForm botId="1" apiBaseUrl="http://api" initialSettings={initialSettings} />);
    const field = screen.getByLabelText(/макс\. размер/i);
    fireEvent.change(field, { target: { value: "" } });
    fireEvent.blur(field);

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(api.patchBotSettings).not.toHaveBeenCalled();
    expect(field).toHaveValue(16);
  });

  it("rejects a media size of 0", async () => {
    render(<BotSettingsForm botId="1" apiBaseUrl="http://api" initialSettings={initialSettings} />);
    const field = screen.getByLabelText(/макс\. размер/i);
    fireEvent.change(field, { target: { value: "0" } });
    fireEvent.blur(field);

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(api.patchBotSettings).not.toHaveBeenCalled();
  });

  it("rejects a media size above the 64 MB ceiling", async () => {
    render(<BotSettingsForm botId="1" apiBaseUrl="http://api" initialSettings={initialSettings} />);
    const field = screen.getByLabelText(/макс\. размер/i);
    fireEvent.change(field, { target: { value: "500" } });
    fireEvent.blur(field);

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(api.patchBotSettings).not.toHaveBeenCalled();
  });

  it("rejects an empty media fallback text", async () => {
    render(<BotSettingsForm botId="1" apiBaseUrl="http://api" initialSettings={initialSettings} />);
    const field = screen.getByLabelText(/заглушка на неподдерживаемое медиа/i);
    fireEvent.change(field, { target: { value: "   " } });
    fireEvent.blur(field);

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(api.patchBotSettings).not.toHaveBeenCalled();
  });

  it("rejects an empty reaction emoji", async () => {
    render(<BotSettingsForm botId="1" apiBaseUrl="http://api" initialSettings={initialSettings} />);
    const field = screen.getByLabelText(/эмодзи реакции/i);
    fireEvent.change(field, { target: { value: "   " } });
    fireEvent.blur(field);

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(api.patchBotSettings).not.toHaveBeenCalled();
  });
});
