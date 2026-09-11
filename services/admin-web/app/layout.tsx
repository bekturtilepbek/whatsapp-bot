import type { ReactNode } from "react";
import { AppHeader } from "@/components/AppHeader";
import { ToastProvider } from "@/components/ToastProvider";
import "./globals.css";

export const metadata = {
  title: "Панель ботов",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ru">
      <body>
        <ToastProvider>
          <AppHeader />
          {children}
        </ToastProvider>
      </body>
    </html>
  );
}
