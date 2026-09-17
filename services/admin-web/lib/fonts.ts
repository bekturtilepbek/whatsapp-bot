// next/font/google самохостит файлы шрифтов на билде (без внешнего запроса
// в браузере и без layout shift от системного фолбэка) — единственное место,
// где шрифты объявляются; остальной код обращается к ним только через
// Tailwind-утилиты font-sans/font-mono (см. @theme в globals.css), никогда
// не импортирует plexSans/plexMono напрямую.
import { IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";

export const plexSans = IBM_Plex_Sans({
  subsets: ["latin", "cyrillic"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-plex-sans",
  display: "swap",
});

export const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-plex-mono",
  display: "swap",
});
