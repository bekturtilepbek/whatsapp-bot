"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchBot, logoutBot, qrImageUrl, type Bot } from "@/lib/api";
import { useToast } from "@/components/ToastProvider";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";

interface QrPanelProps {
  initialBot: Bot;
  apiBaseUrl: string;
  /** 5с по умолчанию (FEATURES.md 6.1) — тесты передают меньшее значение
   * вместо фейковых таймеров. */
  pollIntervalMs?: number;
}

export function QrPanel({ initialBot, apiBaseUrl, pollIntervalMs = 5000 }: QrPanelProps) {
  const { showError, showSuccess } = useToast();
  const [bot, setBot] = useState<Bot>(initialBot);
  const [qrUrl, setQrUrl] = useState<string | null>(null);
  const [loggingOut, setLoggingOut] = useState(false);
  // Намеренно НЕ toast: это статус фонового поллинга (каждые pollIntervalMs,
  // 5с в проде), не результат одноразового действия пользователя — toast на
  // каждый неудачный опрос копился бы бесконечной стопкой, пока не
  // восстановится сеть. Постоянный инлайн-баннер здесь уместнее (FEATURES.md
  // 6.5 про алерты РЕЗУЛЬТАТА действия, не про живой статус соединения).
  const [pollError, setPollError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const updated = await fetchBot(apiBaseUrl, initialBot.id);
      setPollError(null);
      if (!updated) return;
      setBot(updated);
      if (!updated.linked_at) {
        // Перегенерируем URL — cache-busting подхватывает ротацию QR (~20с).
        setQrUrl(qrImageUrl(apiBaseUrl, initialBot.id));
      }
    } catch (err) {
      setPollError(err instanceof Error ? err.message : "Не удалось обновить статус");
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
    setLoggingOut(true);
    try {
      await logoutBot(apiBaseUrl, bot.id);
      showSuccess("Номер отключён");
    } catch (err) {
      showError(err instanceof Error ? err.message : "Не удалось отключить номер");
    } finally {
      setLoggingOut(false);
    }
    // refresh() безопасен всегда (сам ловит свои ошибки) — вызываем и при
    // успехе, и при неудаче logout, чтобы показать актуальное состояние.
    await refresh();
  };

  if (bot.linked_at) {
    return (
      <Card className="p-5">
        <p className="text-sm text-ink">
          Подключён: <span className="font-mono">{bot.phone}</span>
        </p>
        <div className="mt-3">
          <Button variant="danger" onClick={() => void handleLogout()} disabled={loggingOut}>
            {loggingOut ? "Отключаем…" : "Отключить"}
          </Button>
        </div>
        {pollError && (
          <p role="alert" className="mt-3 text-sm text-danger">
            {pollError}
          </p>
        )}
      </Card>
    );
  }

  return (
    <Card className="p-5">
      <p className="text-sm text-ink">Отсканируйте QR в WhatsApp на телефоне</p>
      {qrUrl && (
        // eslint-disable-next-line @next/next/no-img-element -- PNG отдаёт api напрямую, не статический ассет Next.js
        <img
          src={qrUrl}
          alt="QR-код для подключения WhatsApp"
          width={300}
          height={300}
          className="mt-3 rounded-md border border-border"
        />
      )}
      {pollError && (
        <p role="alert" className="mt-3 text-sm text-danger">
          {pollError}
        </p>
      )}
    </Card>
  );
}
