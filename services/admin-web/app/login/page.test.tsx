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

it("shakes and reddens both fields, and blocks the action, when submitted empty", async () => {
  render(<LoginPage />);
  fireEvent.click(screen.getByRole("button", { name: /войти/i }));

  expect(await screen.findByRole("alert")).toHaveTextContent(/введите email и пароль/i);
  expect(login).not.toHaveBeenCalled();
  expect(screen.getByLabelText("Email")).toHaveAttribute("aria-invalid", "true");
  expect(screen.getByLabelText("Пароль")).toHaveAttribute("aria-invalid", "true");
  expect(screen.getByText("Email").closest("label")).toHaveClass("text-danger");
  expect(screen.getByText("Пароль").closest("label")).toHaveClass("text-danger");
});

it("clears the invalid marker on a field once the user starts typing", async () => {
  render(<LoginPage />);
  fireEvent.click(screen.getByRole("button", { name: /войти/i }));
  await screen.findByRole("alert");
  expect(screen.getByLabelText("Email")).toHaveAttribute("aria-invalid", "true");

  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "a@b.com" } });

  expect(screen.getByLabelText("Email")).not.toHaveAttribute("aria-invalid");
});
