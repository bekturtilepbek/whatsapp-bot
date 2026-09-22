"use client";

import { useEffect, useState } from "react";

const STORAGE_KEY = "theme";

type Theme = "light" | "dark";

function applyTheme(theme: Theme) {
  if (theme === "dark") {
    document.documentElement.setAttribute("data-theme", "dark");
  } else {
    document.documentElement.removeAttribute("data-theme");
  }
}

/** Тумблер светлая/тёмная — без auto-detect по prefers-color-scheme,
 * дефолт всегда светлая, пока юзер явно не переключил (подтверждено
 * пользователем). Реальное значение до гидратации выставляет инлайн-
 * скрипт в app/layout.tsx (не этот компонент — иначе первый кадр мигнул
 * бы светлым перед переключением на сохранённую тёмную). */
export function ThemeToggle() {
  // "light" здесь — не дефолт темы, а просто то же самое исходное
  // значение, что и в SSR-разметке (атрибут ещё не читаем) — избегаем
  // hydration mismatch, тот же приём, что и в QrPanel/PromptEditor.
  const [theme, setTheme] = useState<Theme>("light");

  useEffect(() => {
    const current =
      document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
    setTheme(current);
  }, []);

  const toggle = () => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    applyTheme(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // localStorage недоступен (приватный режим и т.п.) — тема просто не переживёт перезагрузку
    }
    setTheme(next);
  };

  const label = theme === "dark" ? "Включить светлую тему" : "Включить тёмную тему";

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={label}
      title={label}
      className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-ink-soft hover:bg-surface-alt hover:text-ink"
    >
      {theme === "dark" ? (
        <svg
          viewBox="0 0 20 20"
          width="16"
          height="16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <circle cx="10" cy="10" r="3.5" />
          <path d="M10 2.5v1.5M10 16v1.5M3.4 3.4l1.1 1.1M15.5 15.5l1.1 1.1M2.5 10H4M16 10h1.5M3.4 16.6l1.1-1.1M15.5 4.5l1.1-1.1" />
        </svg>
      ) : (
        <svg viewBox="0 0 20 20" width="16" height="16" fill="currentColor" aria-hidden="true">
          <path d="M10.8 2.3a7.7 7.7 0 1 0 6.9 11.4.55.55 0 0 0-.6-.8 6.1 6.1 0 0 1-7.6-7.6.55.55 0 0 0-.7-.7Z" />
        </svg>
      )}
    </button>
  );
}
