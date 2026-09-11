"use client";

// FEATURES.md 6.5 — toast-алерты вместо блочных. Все 23 (реально 11)
// существующих места вывода ошибок были инлайн-блоками в разметке формы
// (`{error && <p role="alert">...}`) — не исчезали сами, требовали
// взаимодействия/навигации. Успех действия нигде не подтверждался явно.
//
// V1 (эталон FEATURES.md) гасил флеш-сообщение через cookie-middleware —
// здесь не подходит: все 23 места клиентские (useState + fetch через
// lib/api.ts), пользователь и так остаётся на той же странице, cookie-флеш
// нужен только для флеша МЕЖДУ навигациями (как у V1's блочных форм).
// Простой client-side Context ближе к тому, что реально происходит.

import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";

type ToastKind = "error" | "success";

interface Toast {
  id: number;
  message: string;
  kind: ToastKind;
}

interface ToastContextValue {
  showError: (message: string) => void;
  showSuccess: (message: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

// Ошибку читают дольше, чем короткое подтверждение успеха — оба значения
// внутри диапазона V1 (5-10с).
const ERROR_DURATION_MS = 8000;
const SUCCESS_DURATION_MS = 6000;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  // useState-счётчик, не crypto.randomUUID(): id нужен только для React key
  // и последующего removeToast в рамках ЭТОЙ вкладки — не персистентный
  // идентификатор, коллизии не имеют цены.
  const nextId = useRef(0);

  const removeToast = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const showToast = useCallback(
    (message: string, kind: ToastKind) => {
      const id = nextId.current++;
      setToasts((current) => [...current, { id, message, kind }]);
      const duration = kind === "error" ? ERROR_DURATION_MS : SUCCESS_DURATION_MS;
      setTimeout(() => removeToast(id), duration);
    },
    [removeToast],
  );

  const showError = useCallback((message: string) => showToast(message, "error"), [showToast]);
  const showSuccess = useCallback((message: string) => showToast(message, "success"), [showToast]);

  return (
    <ToastContext.Provider value={{ showError, showSuccess }}>
      {children}
      <div
        style={{
          position: "fixed",
          bottom: "1rem",
          right: "1rem",
          display: "flex",
          flexDirection: "column",
          gap: "0.5rem",
          zIndex: 1000,
        }}
      >
        {toasts.map((toast) => (
          <div
            key={toast.id}
            role={toast.kind === "error" ? "alert" : "status"}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "0.75rem",
              padding: "0.75rem 1rem",
              borderRadius: "4px",
              boxShadow: "0 1px 4px rgba(0,0,0,0.2)",
              background: toast.kind === "error" ? "#fdecea" : "#e8f5e9",
              color: toast.kind === "error" ? "crimson" : "#1e4620",
              maxWidth: "24rem",
            }}
          >
            <span>{toast.message}</span>
            <button
              type="button"
              aria-label="Закрыть уведомление"
              onClick={() => removeToast(toast.id)}
              style={{ background: "none", border: "none", cursor: "pointer", fontSize: "1rem" }}
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const value = useContext(ToastContext);
  if (!value) {
    throw new Error("useToast must be used within a ToastProvider");
  }
  return value;
}
