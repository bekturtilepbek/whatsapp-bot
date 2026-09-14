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
          <div className="min-w-0 flex-1 overflow-x-hidden px-8 py-7">{children}</div>
        </ToastProvider>
      </body>
    </html>
  );
}
