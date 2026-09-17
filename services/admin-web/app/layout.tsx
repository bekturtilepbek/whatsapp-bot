import type { ReactNode } from "react";
import { Sidebar } from "@/components/Sidebar";
import { ToastProvider } from "@/components/ToastProvider";
import { plexMono, plexSans } from "@/lib/fonts";
import "./globals.css";

export const metadata = {
  title: "Панель ботов",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ru" className={`${plexSans.variable} ${plexMono.variable}`}>
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
