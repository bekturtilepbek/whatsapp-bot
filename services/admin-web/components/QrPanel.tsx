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
  const [qrUrl, setQrUrl] = useState<string | null>(null);
  const [loggingOut, setLoggingOut] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const updated = await fetchBot(apiBaseUrl, initialBot.id);
      setError(null);
      if (!updated) return;
      setBot(updated);
      if (!updated.linked_at) {
        // Перегенерируем URL — cache-busting подхватывает ротацию QR (~20с).
        setQrUrl(qrImageUrl(apiBaseUrl, initialBot.id));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось обновить статус");
    }
  }, [apiBaseUrl, initialBot.id]);

  useEffect(() => {
    const timer = setInterval(() => {
      void refresh();
    }, pollIntervalMs);
    return () => clearInterval(timer);
  }, [refresh, pollIntervalMs]);

  // Инициализировать QR-код только на клиенте после монтирования,
  // чтобы избежать гидрацион-mismatch между SSR и клиентом.
  useEffect(() => {
    setQrUrl(qrImageUrl(apiBaseUrl, initialBot.id));
  }, [apiBaseUrl, initialBot.id]);

  const handleLogout = async () => {
    setError(null);
    setLoggingOut(true);
    try {
      await logoutBot(apiBaseUrl, bot.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось отключить номер");
    } finally {
      setLoggingOut(false);
    }
    // refresh() безопасен всегда (сам ловит свои ошибки) — вызываем и при
    // успехе, и при неудаче logout, чтобы показать актуальное состояние.
    await refresh();
  };

  if (bot.linked_at) {
    return (
      <div>
        <p>Подключён: {bot.phone}</p>
        <button onClick={() => void handleLogout()} disabled={loggingOut}>
          {loggingOut ? "Отключаем…" : "Отключить"}
        </button>
        {error && (
          <p role="alert" style={{ color: "crimson" }}>
            {error}
          </p>
        )}
      </div>
    );
  }

  return (
    <div>
      <p>Отсканируйте QR в WhatsApp на телефоне</p>
      {qrUrl && (
        // eslint-disable-next-line @next/next/no-img-element -- PNG отдаёт api напрямую, не статический ассет Next.js
        <img src={qrUrl} alt="QR-код для подключения WhatsApp" width={300} height={300} />
      )}
      {error && (
        <p role="alert" style={{ color: "crimson" }}>
          {error}
        </p>
      )}
    </div>
  );
}
