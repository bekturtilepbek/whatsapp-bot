import type { ReactNode } from "react";
import { Sidebar } from "@/components/Sidebar";
import { ToastProvider } from "@/components/ToastProvider";
import { inter, plexMono } from "@/lib/fonts";
import "./globals.css";

export const metadata = {
  title: "Espada.ai",
};

// Выполняется синхронно ДО первой отрисовки <body> (обычный <script> в
// <head>, не async/defer/module) — иначе на возврате пользователя с
// сохранённой тёмной темой первый кадр на долю секунды мигнул бы светлым,
// пока React не гидратировался и ThemeToggle не прочитал localStorage сам.
// Дефолт — светлая: при отсутствии сохранённого значения атрибут просто
// не выставляется, :root уже светлый без него.
const THEME_INIT_SCRIPT = `
(function () {
  try {
    if (localStorage.getItem("theme") === "dark") {
      document.documentElement.setAttribute("data-theme", "dark");
    }
  } catch (e) {}
})();
`;

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    // suppressHydrationWarning — только на этом элементе (не рекурсивно):
    // THEME_INIT_SCRIPT ниже правит data-theme ДО гидратации, сервер его не
    // знает (localStorage недоступен при SSR) — без этого пропа React считает
    // это багом рассинхрона разметки и шумит в консоли на каждой загрузке
    // страницы у любого, кто хоть раз включал тёмную тему.
    <html
      lang="ru"
      className={`${inter.variable} ${plexMono.variable}`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="m-0 flex min-h-screen bg-canvas font-sans text-ink">
        <ToastProvider>
          <Sidebar />
          {/* Без overflow-x-hidden здесь: он делал этот div скролл-контейнером,
              и на узком окне Next.js после client-side навигации переводит
              фокус на <h1> страницы — браузер сам горизонтально проскраливал
              этот контейнер, чтобы показать фокус, обрезая заголовок и первые
              вкладки слева (живая проверка, docker compose, 2026-09-15).
              Горизонтальный overflow при нехватке места теперь — забота
              самой Tabs (components/ui/Tabs.tsx), не всей страницы. */}
          <div className="min-w-0 flex-1 px-10 py-8">{children}</div>
        </ToastProvider>
      </body>
    </html>
  );
}
