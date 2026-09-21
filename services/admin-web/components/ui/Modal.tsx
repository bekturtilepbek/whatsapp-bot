"use client";

import { useEffect, type ReactNode } from "react";

interface ModalProps {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  /** Класс max-w-* контейнера — под контент разной ширины (список версий
   * промпта шире, чем обычный диалог подтверждения). */
  widthClassName?: string;
}

/** Универсальное модальное окно поверх контента страницы — в отличие от
 * ConfirmDialog (узкий сценарий подтверждения с готовыми кнопками), здесь
 * произвольный children. Escape и клик по фону закрывают; клик внутри
 * карточки — нет. */
export function Modal({ open, title, onClose, children, widthClassName = "max-w-lg" }: ModalProps) {
  useEffect(() => {
    if (!open) {
      return;
    }
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, onClose]);

  if (!open) {
    return null;
  }

  return (
    <div
      className="fixed inset-0 z-[1000] flex items-center justify-center bg-ink/40 p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
        className={`flex max-h-[85vh] w-full ${widthClassName} flex-col rounded-2xl border border-border bg-surface p-5 shadow-elevated`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex shrink-0 items-center justify-between gap-4">
          <p id="modal-title" className="text-sm font-bold text-ink">
            {title}
          </p>
          <button
            type="button"
            aria-label="Закрыть"
            onClick={onClose}
            className="p-0 text-lg leading-none text-ink-soft hover:text-ink"
          >
            ×
          </button>
        </div>
        <div className="overflow-y-auto">{children}</div>
      </div>
    </div>
  );
}
