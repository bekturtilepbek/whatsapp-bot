import { afterEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@/lib/test-utils";
import { ResponsibleUserForm } from "@/components/ResponsibleUserForm";
import * as api from "@/lib/api";
import type { Bot, PrompterBrief } from "@/lib/api";

const refreshMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: refreshMock }),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    patchBotResponsibleUser: vi.fn(),
  };
});

const updatedBot: Bot = {
  id: "b1",
  name: "Bot",
  enabled: true,
  phone: null,
  linked_at: null,
  system_prompt: "",
  image_prompt: null,
  pdf_prompt: null,
  responsible_user_id: "p2",
};

const prompters: PrompterBrief[] = [
  { id: "p1", email: "prompter1@example.com" },
  { id: "p2", email: "prompter2@example.com" },
];

afterEach(() => {
  vi.clearAllMocks();
});

it("shows the current responsible user by default", () => {
  render(
    <ResponsibleUserForm
      botId="b1"
      apiBaseUrl="http://api"
      initialResponsibleUserId="p1"
      prompters={prompters}
    />,
  );
  expect(screen.getByLabelText("Ответственный")).toHaveValue("p1");
});

it("defaults to 'Не назначен' when there is no responsible user", () => {
  render(
    <ResponsibleUserForm
      botId="b1"
      apiBaseUrl="http://api"
      initialResponsibleUserId={null}
      prompters={prompters}
    />,
  );
  expect(screen.getByLabelText("Ответственный")).toHaveValue("");
});

it("saves the newly selected responsible user and refreshes", async () => {
  vi.mocked(api.patchBotResponsibleUser).mockResolvedValue(updatedBot);
  render(
    <ResponsibleUserForm
      botId="b1"
      apiBaseUrl="http://api"
      initialResponsibleUserId="p1"
      prompters={prompters}
    />,
  );

  fireEvent.change(screen.getByLabelText("Ответственный"), { target: { value: "p2" } });
  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));

  await waitFor(() => {
    expect(api.patchBotResponsibleUser).toHaveBeenCalledWith("http://api", "b1", "p2");
  });
  expect(refreshMock).toHaveBeenCalled();
  expect(screen.getByRole("status")).toHaveTextContent(/ответственный сохранён/i);
});

it("saves null when unassigning the responsible user", async () => {
  vi.mocked(api.patchBotResponsibleUser).mockResolvedValue({
    ...updatedBot,
    responsible_user_id: null,
  });
  render(
    <ResponsibleUserForm
      botId="b1"
      apiBaseUrl="http://api"
      initialResponsibleUserId="p1"
      prompters={prompters}
    />,
  );

  fireEvent.change(screen.getByLabelText("Ответственный"), { target: { value: "" } });
  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));

  await waitFor(() => {
    expect(api.patchBotResponsibleUser).toHaveBeenCalledWith("http://api", "b1", null);
  });
});

it("shows an error and does not refresh when saving fails", async () => {
  vi.mocked(api.patchBotResponsibleUser).mockRejectedValue(new Error("save failed"));
  render(
    <ResponsibleUserForm
      botId="b1"
      apiBaseUrl="http://api"
      initialResponsibleUserId="p1"
      prompters={prompters}
    />,
  );

  fireEvent.change(screen.getByLabelText("Ответственный"), { target: { value: "p2" } });
  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent(/save failed/i);
  });
  expect(refreshMock).not.toHaveBeenCalled();
});
