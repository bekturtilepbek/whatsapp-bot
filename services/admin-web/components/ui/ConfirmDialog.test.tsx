import { expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";

it("renders nothing when closed", () => {
  render(
    <ConfirmDialog open={false} title="Удалить файл?" onConfirm={vi.fn()} onCancel={vi.fn()} />,
  );
  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
});

it("shows the title and optional description when open", () => {
  render(
    <ConfirmDialog
      open
      title="Удалить файл?"
      description="Это действие необратимо."
      onConfirm={vi.fn()}
      onCancel={vi.fn()}
    />,
  );
  expect(screen.getByRole("alertdialog")).toBeInTheDocument();
  expect(screen.getByText("Удалить файл?")).toBeInTheDocument();
  expect(screen.getByText("Это действие необратимо.")).toBeInTheDocument();
});

it("calls onConfirm when the confirm button is clicked", () => {
  const onConfirm = vi.fn();
  render(<ConfirmDialog open title="Удалить файл?" onConfirm={onConfirm} onCancel={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Удалить" }));
  expect(onConfirm).toHaveBeenCalledTimes(1);
});

it("calls onCancel when the cancel button is clicked", () => {
  const onCancel = vi.fn();
  render(<ConfirmDialog open title="Удалить файл?" onConfirm={vi.fn()} onCancel={onCancel} />);
  fireEvent.click(screen.getByRole("button", { name: "Отмена" }));
  expect(onCancel).toHaveBeenCalledTimes(1);
});

it("calls onCancel when clicking the backdrop", () => {
  const onCancel = vi.fn();
  render(<ConfirmDialog open title="Удалить файл?" onConfirm={vi.fn()} onCancel={onCancel} />);
  fireEvent.click(screen.getByRole("alertdialog").parentElement as HTMLElement);
  expect(onCancel).toHaveBeenCalledTimes(1);
});

it("does not call onCancel when clicking inside the dialog", () => {
  const onCancel = vi.fn();
  render(<ConfirmDialog open title="Удалить файл?" onConfirm={vi.fn()} onCancel={onCancel} />);
  fireEvent.click(screen.getByRole("alertdialog"));
  expect(onCancel).not.toHaveBeenCalled();
});

it("calls onCancel on Escape", () => {
  const onCancel = vi.fn();
  render(<ConfirmDialog open title="Удалить файл?" onConfirm={vi.fn()} onCancel={onCancel} />);
  fireEvent.keyDown(window, { key: "Escape" });
  expect(onCancel).toHaveBeenCalledTimes(1);
});

it("supports custom confirm/cancel labels", () => {
  render(
    <ConfirmDialog
      open
      title="Отключить бота?"
      confirmLabel="Отключить"
      cancelLabel="Оставить"
      onConfirm={vi.fn()}
      onCancel={vi.fn()}
    />,
  );
  expect(screen.getByRole("button", { name: "Отключить" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Оставить" })).toBeInTheDocument();
});
