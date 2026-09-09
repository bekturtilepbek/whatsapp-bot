"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchBot, logoutBot, qrImageUrl, type Bot } from "@/lib/api";

interface QrPanelProps {
  initialBot: Bot;
  apiBaseUrl: string;
  /** 5с по умолчанию (FEATURES.md 6.1) — тесты передают меньшее значение
   * вместо фейковых таймеров. */
  pollIntervalMs?: number;
}

export function QrPanel({ initialBot, apiBaseUrl, pollIntervalMs = 5000 }: QrPanelProps) {
  const [bot, setBot] = useState<Bot>(initialBot);
  const [qrUrl, setQrUrl] = useState<string>(() => qrImageUrl(apiBaseUrl, initialBot.id));
  const [loggingOut, setLoggingOut] = useState(false);

  const refresh = useCallback(async () => {
    const updated = await fetchBot(apiBaseUrl, initialBot.id);
    if (!updated) return;
    setBot(updated);
    if (!updated.linked_at) {
      // Перегенерируем URL — cache-busting подхватывает ротацию QR (~20с).
      setQrUrl(qrImageUrl(apiBaseUrl, initialBot.id));
    }
  }, [apiBaseUrl, initialBot.id]);

  useEffect(() => {
    const timer = setInterval(() => {
      void refresh();
    }, pollIntervalMs);
    return () => clearInterval(timer);
  }, [refresh, pollIntervalMs]);

  const handleLogout = async () => {
    setLoggingOut(true);
    try {
      await logoutBot(apiBaseUrl, bot.id);
      await refresh();
    } finally {
      setLoggingOut(false);
    }
  };

  if (bot.linked_at) {
    return (
      <div>
        <p>Подключён: {bot.phone}</p>
        <button onClick={() => void handleLogout()} disabled={loggingOut}>
          {loggingOut ? "Отключаем…" : "Отключить"}
        </button>
      </div>
    );
  }

  return (
    <div>
      <p>Отсканируйте QR в WhatsApp на телефоне</p>
      {/* eslint-disable-next-line @next/next/no-img-element -- PNG отдаёт api напрямую, не статический ассет Next.js */}
      <img src={qrUrl} alt="QR-код для подключения WhatsApp" width={300} height={300} />
    </div>
  );
}
