import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { Sidebar } from "@/components/Sidebar";
import { fetchCurrentUser } from "@/lib/currentUser";

// render(await Sidebar()) резолвит только один уровень async — безопасно,
// пока ни один child Sidebar не является сам async Server Component-ом.

vi.mock("@/lib/currentUser", () => ({
  fetchCurrentUser: vi.fn(),
  PLATFORM_WIDE_ROLES: ["superadmin", "admin"],
}));
vi.mock("@/app/login/actions", () => ({
  logout: vi.fn(),
}));

const mockedFetchCurrentUser = vi.mocked(fetchCurrentUser);

it("renders nothing when there is no logged-in user", async () => {
  mockedFetchCurrentUser.mockResolvedValue(null);
  const { container } = render(await Sidebar());
  expect(container).toBeEmptyDOMElement();
});

it("shows only the Боты link and the user's email for a client", async () => {
  mockedFetchCurrentUser.mockResolvedValue({ email: "client@example.com", role: "client" });
  render(await Sidebar());
  expect(screen.getByRole("link", { name: "Боты" })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Дашборд" })).not.toBeInTheDocument();
  expect(screen.getByText("client@example.com")).toBeInTheDocument();
});

it("shows only the Боты link for a prompter (platform-wide screens are superadmin/admin only)", async () => {
  mockedFetchCurrentUser.mockResolvedValue({ email: "prompter@example.com", role: "prompter" });
  render(await Sidebar());
  expect(screen.queryByRole("link", { name: "Дашборд" })).not.toBeInTheDocument();
});

it("shows the platform navigation group, without Пользователи, for an admin", async () => {
  mockedFetchCurrentUser.mockResolvedValue({ email: "admin@example.com", role: "admin" });
  render(await Sidebar());
  expect(screen.getByRole("link", { name: "Дашборд" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Аудит-лог" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Расходы" })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Пользователи" })).not.toBeInTheDocument();
});

it("shows the full platform navigation group, including Пользователи, for a superadmin", async () => {
  mockedFetchCurrentUser.mockResolvedValue({ email: "owner@example.com", role: "superadmin" });
  render(await Sidebar());
  expect(screen.getByRole("link", { name: "Дашборд" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Пользователи" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Аудит-лог" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Расходы" })).toBeInTheDocument();
});
