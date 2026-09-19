import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@/lib/test-utils";
import { PromptEditor } from "@/components/PromptEditor";
import * as api from "@/lib/api";
import type { PromptVersion } from "@/lib/api";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    patchBotPrompt: vi.fn(),
    fetchPromptVersions: vi.fn(),
  };
});

const existingVersion: PromptVersion = {
  id: "v1",
  body: "старый текст",
  author: "admin",
  created_at: "2026-09-08T10:00:00Z",
};

afterEach(() => {
  vi.clearAllMocks();
});

it("renders the current prompt body with history hidden behind a link", () => {
  render(
    <PromptEditor
      botId="1"
      apiBaseUrl="http://api"
      kind="main"
      label="Основной промпт"
      initialBody="текущий текст"
      initialVersions={[existingVersion]}
    />,
  );
  expect(screen.getByRole("textbox")).toHaveValue("текущий текст");
  expect(screen.queryByText(/старый текст/)).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: /история изменений/i }));

  expect(screen.getByText(/старый текст/)).toBeInTheDocument();
});

it("saves the edited body and refreshes version history", async () => {
  vi.mocked(api.patchBotPrompt).mockResolvedValue({
    id: "1",
    name: "Bot",
    enabled: true,
    phone: null,
    linked_at: null,
    system_prompt: "новый текст",
    image_prompt: null,
    pdf_prompt: null,
  });
  const newVersion: PromptVersion = {
    id: "v2",
    body: "новый текст",
    author: "admin",
    created_at: "2026-09-09T10:00:00Z",
  };
  vi.mocked(api.fetchPromptVersions).mockResolvedValue([newVersion, existingVersion]);

  render(
    <PromptEditor
      botId="1"
      apiBaseUrl="http://api"
      kind="main"
      label="Основной промпт"
      initialBody="текущий текст"
      initialVersions={[existingVersion]}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: /история изменений/i }));
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "новый текст" } });
  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));

  await waitFor(() => {
    expect(api.patchBotPrompt).toHaveBeenCalledWith("http://api", "1", "main", "новый текст");
  });
  await waitFor(() => {
    expect(screen.getAllByText(/новый текст/).length).toBeGreaterThan(0);
  });
  expect(screen.getByRole("status")).toHaveTextContent(/сохранено/i);
});

it("rolls back to a past version with one click", async () => {
  vi.mocked(api.patchBotPrompt).mockResolvedValue({
    id: "1",
    name: "Bot",
    enabled: true,
    phone: null,
    linked_at: null,
    system_prompt: "старый текст",
    image_prompt: null,
    pdf_prompt: null,
  });
  vi.mocked(api.fetchPromptVersions).mockResolvedValue([existingVersion]);

  render(
    <PromptEditor
      botId="1"
      apiBaseUrl="http://api"
      kind="main"
      label="Основной промпт"
      initialBody="текущий текст"
      initialVersions={[existingVersion]}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: /история изменений/i }));
  fireEvent.click(screen.getByRole("button", { name: /откатить/i }));

  await waitFor(() => {
    expect(api.patchBotPrompt).toHaveBeenCalledWith("http://api", "1", "main", "старый текст");
  });
});

it("shows an error when saving fails", async () => {
  vi.mocked(api.patchBotPrompt).mockRejectedValue(new Error("save failed"));

  render(
    <PromptEditor
      botId="1"
      apiBaseUrl="http://api"
      kind="main"
      label="Основной промпт"
      initialBody="текущий текст"
      initialVersions={[]}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent(/save failed/i);
  });
});

it("renders version history as a table once revealed", () => {
  render(
    <PromptEditor
      botId="1"
      apiBaseUrl="http://api"
      kind="main"
      label="Основной промпт"
      initialBody="текущий текст"
      initialVersions={[existingVersion]}
    />,
  );
  expect(screen.queryByRole("table")).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: /история изменений/i }));

  expect(screen.getByRole("table")).toBeInTheDocument();
});
