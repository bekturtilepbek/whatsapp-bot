import { afterEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@/lib/test-utils";
import LoginPage from "@/app/login/page";
import { login } from "@/app/login/actions";

vi.mock("@/app/login/actions", () => ({
  login: vi.fn(),
}));

afterEach(() => {
  vi.clearAllMocks();
});

function submit() {
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "a@b.com" } });
  fireEvent.change(screen.getByLabelText("Пароль"), { target: { value: "secret" } });
  fireEvent.click(screen.getByRole("button", { name: /войти/i }));
}

it("shows an error toast when login fails", async () => {
  vi.mocked(login).mockResolvedValue("Неверный email или пароль");
  render(<LoginPage />);

  submit();

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent(/неверный email или пароль/i);
  });
});

it("shows a fresh toast on a second failed attempt with the same message", async () => {
  // Регрессия: naive useEffect по [error] не перезапустился бы на второй
  // попытке, если её текст совпадает с первой — здесь ловим переход
  // pending true→false, а не значение error.
  vi.mocked(login).mockResolvedValue("Неверный email или пароль");
  render(<LoginPage />);

  submit();
  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent(/неверный email или пароль/i);
  });

  submit();
  await waitFor(() => {
    expect(screen.getAllByRole("alert")).toHaveLength(2);
  });
});

it("does not show a toast while no submission has happened yet", () => {
  render(<LoginPage />);
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
