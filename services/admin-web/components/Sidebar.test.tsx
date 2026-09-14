import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { Sidebar } from "@/components/Sidebar";
import { fetchCurrentUser } from "@/lib/currentUser";

vi.mock("@/lib/currentUser", () => ({
  fetchCurrentUser: vi.fn(),
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

it("shows only the Боты link and the user's email for a non-owner", async () => {
  mockedFetchCurrentUser.mockResolvedValue({ email: "client@example.com", is_platform_owner: false });
  render(await Sidebar());
  expect(screen.getByRole("link", { name: "Боты" })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Дашборд" })).not.toBeInTheDocument();
  expect(screen.getByText("client@example.com")).toBeInTheDocument();
});

it("shows the platform-owner navigation group for an owner", async () => {
  mockedFetchCurrentUser.mockResolvedValue({ email: "owner@example.com", is_platform_owner: true });
  render(await Sidebar());
  expect(screen.getByRole("link", { name: "Дашборд" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Пользователи" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Аудит-лог" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Расходы" })).toBeInTheDocument();
});
