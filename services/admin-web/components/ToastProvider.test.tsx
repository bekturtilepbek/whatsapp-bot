import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { ToastProvider, useToast } from "@/components/ToastProvider";

function Trigger() {
  const { showError, showSuccess } = useToast();
  return (
    <>
      <button onClick={() => showError("Что-то сломалось")}>error</button>
      <button onClick={() => showSuccess("Сохранено")}>success</button>
    </>
  );
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

it("shows an error toast with role=alert", () => {
  render(
    <ToastProvider>
      <Trigger />
    </ToastProvider>,
  );
  fireEvent.click(screen.getByText("error"));
  expect(screen.getByRole("alert")).toHaveTextContent("Что-то сломалось");
});

it("shows a success toast with role=status", () => {
  render(
    <ToastProvider>
      <Trigger />
    </ToastProvider>,
  );
  fireEvent.click(screen.getByText("success"));
  expect(screen.getByRole("status")).toHaveTextContent("Сохранено");
});

it("auto-dismisses a success toast after its duration", () => {
  render(
    <ToastProvider>
      <Trigger />
    </ToastProvider>,
  );
  fireEvent.click(screen.getByText("success"));
  expect(screen.queryByRole("status")).not.toBeNull();

  act(() => {
    vi.advanceTimersByTime(6000);
  });
  expect(screen.queryByRole("status")).toBeNull();
});

it("keeps an error toast alive longer than a success toast", () => {
  render(
    <ToastProvider>
      <Trigger />
    </ToastProvider>,
  );
  fireEvent.click(screen.getByText("error"));

  act(() => {
    vi.advanceTimersByTime(6000); // прошёл бы success-таймаут, но не error-
  });
  expect(screen.queryByRole("alert")).not.toBeNull();

  act(() => {
    vi.advanceTimersByTime(2000); // теперь и error-таймаут (8с) истёк
  });
  expect(screen.queryByRole("alert")).toBeNull();
});

it("stacks multiple toasts and dismisses one manually", () => {
  render(
    <ToastProvider>
      <Trigger />
    </ToastProvider>,
  );
  fireEvent.click(screen.getByText("error"));
  fireEvent.click(screen.getByText("success"));
  expect(screen.getByRole("alert")).toBeTruthy();
  expect(screen.getByRole("status")).toBeTruthy();

  const [firstCloseButton] = screen.getAllByLabelText("Закрыть уведомление");
  fireEvent.click(firstCloseButton);
  // Первая кнопка закрытия — у error-toast (добавлен раньше) — status остаётся
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.getByRole("status")).toBeTruthy();
});

it("throws when useToast is used outside a ToastProvider", () => {
  const BareTrigger = () => {
    useToast();
    return null;
  };
  // React логирует ошибку в консоль при выбросе внутри рендера — подавляем
  // именно этот шум, не проглатываем сам assert.
  const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
  expect(() => render(<BareTrigger />)).toThrow("useToast must be used within a ToastProvider");
  consoleError.mockRestore();
});
