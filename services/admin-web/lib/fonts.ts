// next/font/google самохостит файлы шрифтов на билде (без внешнего запроса
// в браузере и без layout shift от системного фолбэка) — единственное место,
// где шрифты объявляются; остальной код обращается к ним только через
// Tailwind-утилиты font-sans/font-mono (см. @theme в globals.css), никогда
// не импортирует inter/plexMono напрямую.
//
// Inter — тот же шрифт, что и в старом проекте (bot_management.html,
// central-admin: Inter:wght@400;500;600;700 через Google Fonts) — уже
// проверен на реальных клиентах, отличная поддержка кириллицы. Пришёл на
// смену IBM Plex Sans по прямому запросу пользователя (2026-09-22).
import { IBM_Plex_Mono, Inter } from "next/font/google";

export const inter = Inter({
  subsets: ["latin", "cyrillic"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-inter",
  display: "swap",
});

export const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-plex-mono",
  display: "swap",
});
