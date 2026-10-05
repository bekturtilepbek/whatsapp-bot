import { afterEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@/lib/test-utils";
import { LifecycleStatusForm } from "@/components/LifecycleStatusForm";
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
    patchBotLifecycleStatus: vi.fn(),
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
  lifecycle_status: "frozen",
};

afterEach(() => {
  vi.clearAllMocks();
});

it("shows the current status", () => {
  render(<LifecycleStatusForm botId="b1" apiBaseUrl="http://api" initialStatus="active" />);
  expect(screen.getByLabelText("Статус клиента")).toHaveValue("active");
});

it("offers all four statuses with Russian labels", () => {
  render(<LifecycleStatusForm botId="b1" apiBaseUrl="http://api" initialStatus="active" />);
  const labels = screen.getAllByRole("option").map((o) => o.textContent);
  expect(labels).toEqual(["В разработке", "Подключён", "Заморожен", "Не оплачен"]);
});

it("saves the selected status and refreshes", async () => {
  vi.mocked(api.patchBotLifecycleStatus).mockResolvedValue(updatedBot);
  render(<LifecycleStatusForm botId="b1" apiBaseUrl="http://api" initialStatus="active" />);

  fireEvent.change(screen.getByLabelText("Статус клиента"), { target: { value: "frozen" } });
  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));

  await waitFor(() => {
    expect(api.patchBotLifecycleStatus).toHaveBeenCalledWith("http://api", "b1", "frozen");
  });
  expect(refreshMock).toHaveBeenCalled();
  expect(screen.getByRole("status")).toHaveTextContent(/статус сохранён/i);
});

it("shows an error and does not refresh when saving fails", async () => {
  vi.mocked(api.patchBotLifecycleStatus).mockRejectedValue(new Error("save failed"));
  render(<LifecycleStatusForm botId="b1" apiBaseUrl="http://api" initialStatus="active" />);

  fireEvent.change(screen.getByLabelText("Статус клиента"), { target: { value: "unpaid" } });
  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent(/save failed/i);
  });
  expect(refreshMock).not.toHaveBeenCalled();
});
