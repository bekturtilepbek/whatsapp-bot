import { afterEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { UsersTable } from "@/components/UsersTable";
import * as api from "@/lib/api";
import type { Bot, CabinetUser } from "@/lib/api";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    createUser: vi.fn(),
    grantBotAccess: vi.fn(),
    revokeBotAccess: vi.fn(),
    patchUser: vi.fn(),
  };
});

const bots: Bot[] = [
  {
    id: "bot-1",
    name: "Bot One",
    enabled: true,
    phone: null,
    linked_at: null,
    system_prompt: "",
    image_prompt: null,
    pdf_prompt: null,
  },
  {
    id: "bot-2",
    name: "Bot Two",
    enabled: true,
    phone: null,
    linked_at: null,
    system_prompt: "",
    image_prompt: null,
    pdf_prompt: null,
  },
];

const owner: CabinetUser = {
  id: "owner-1",
  email: "owner@example.com",
  is_platform_owner: true,
  is_active: true,
  bot_ids: [],
};

const users: CabinetUser[] = [
  owner,
  {
    id: "u1",
    email: "client1@example.com",
    is_platform_owner: false,
    is_active: true,
    bot_ids: ["bot-1"],
  },
  {
    id: "u2",
    email: "client2@example.com",
    is_platform_owner: false,
    is_active: false,
    bot_ids: [],
  },
];

afterEach(() => {
  vi.clearAllMocks();
});

it("renders each non-owner user row", () => {
  render(<UsersTable apiBaseUrl="http://api" users={users} bots={bots} />);
  expect(screen.getByText("client1@example.com")).toBeInTheDocument();
  expect(screen.getByText("client2@example.com")).toBeInTheDocument();
});

it("hides the platform owner's own row", () => {
  render(<UsersTable apiBaseUrl="http://api" users={users} bots={bots} />);
  expect(screen.queryByText("owner@example.com")).not.toBeInTheDocument();
});

it("creates a user and adds it to the list", async () => {
  const created: CabinetUser = {
    id: "u3",
    email: "new@example.com",
    is_platform_owner: false,
    is_active: true,
    bot_ids: [],
  };
  vi.mocked(api.createUser).mockResolvedValue(created);
  render(<UsersTable apiBaseUrl="http://api" users={users} bots={bots} />);

  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "new@example.com" } });
  fireEvent.change(screen.getByLabelText("Пароль"), { target: { value: "secret123" } });
  fireEvent.click(screen.getByRole("button", { name: /создать пользователя/i }));

  await waitFor(() => {
    expect(api.createUser).toHaveBeenCalledWith("http://api", {
      email: "new@example.com",
      password: "secret123",
      bot_ids: [],
    });
  });
  expect(await screen.findByText("new@example.com")).toBeInTheDocument();
  expect((screen.getByLabelText("Email") as HTMLInputElement).value).toBe("");
  expect((screen.getByLabelText("Пароль") as HTMLInputElement).value).toBe("");
});

it("shows an error and keeps the form filled when creating fails", async () => {
  vi.mocked(api.createUser).mockRejectedValue(new Error("create failed"));
  render(<UsersTable apiBaseUrl="http://api" users={users} bots={bots} />);

  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "new@example.com" } });
  fireEvent.change(screen.getByLabelText("Пароль"), { target: { value: "secret123" } });
  fireEvent.click(screen.getByRole("button", { name: /создать пользователя/i }));

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent(/create failed/i);
  });
  expect((screen.getByLabelText("Email") as HTMLInputElement).value).toBe("new@example.com");
});

it("grants bot access via checkbox", async () => {
  vi.mocked(api.grantBotAccess).mockResolvedValue(undefined);
  render(<UsersTable apiBaseUrl="http://api" users={users} bots={bots} />);

  const checkbox = screen.getByLabelText("Bot Two: client1@example.com") as HTMLInputElement;
  expect(checkbox.checked).toBe(false);
  fireEvent.click(checkbox);

  await waitFor(() => {
    expect(api.grantBotAccess).toHaveBeenCalledWith("http://api", "u1", "bot-2");
  });
  await waitFor(() => {
    expect(checkbox.checked).toBe(true);
  });
});

it("revokes bot access via checkbox", async () => {
  vi.mocked(api.revokeBotAccess).mockResolvedValue(undefined);
  render(<UsersTable apiBaseUrl="http://api" users={users} bots={bots} />);

  const checkbox = screen.getByLabelText("Bot One: client1@example.com") as HTMLInputElement;
  expect(checkbox.checked).toBe(true);
  fireEvent.click(checkbox);

  await waitFor(() => {
    expect(api.revokeBotAccess).toHaveBeenCalledWith("http://api", "u1", "bot-1");
  });
  await waitFor(() => {
    expect(checkbox.checked).toBe(false);
  });
});

it("shows an error and reverts the checkbox when toggling access fails", async () => {
  vi.mocked(api.grantBotAccess).mockRejectedValue(new Error("access failed"));
  render(<UsersTable apiBaseUrl="http://api" users={users} bots={bots} />);

  const checkbox = screen.getByLabelText("Bot Two: client1@example.com") as HTMLInputElement;
  fireEvent.click(checkbox);

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent(/access failed/i);
  });
  expect(checkbox.checked).toBe(false);
});

it("toggles a user's active status", async () => {
  vi.mocked(api.patchUser).mockResolvedValue({ ...users[2], is_active: true });
  render(<UsersTable apiBaseUrl="http://api" users={users} bots={bots} />);

  const checkbox = screen.getByLabelText("Активен: client2@example.com") as HTMLInputElement;
  expect(checkbox.checked).toBe(false);
  fireEvent.click(checkbox);

  await waitFor(() => {
    expect(api.patchUser).toHaveBeenCalledWith("http://api", "u2", { is_active: true });
  });
  await waitFor(() => {
    expect(checkbox.checked).toBe(true);
  });
});

it("shows an error and reverts the checkbox when toggling active status fails", async () => {
  vi.mocked(api.patchUser).mockRejectedValue(new Error("toggle failed"));
  render(<UsersTable apiBaseUrl="http://api" users={users} bots={bots} />);

  const checkbox = screen.getByLabelText("Активен: client1@example.com") as HTMLInputElement;
  expect(checkbox.checked).toBe(true);
  fireEvent.click(checkbox);

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent(/toggle failed/i);
  });
  expect(checkbox.checked).toBe(true);
});
