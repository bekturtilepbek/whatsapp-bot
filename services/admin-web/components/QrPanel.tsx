"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { fetchBot, logoutBot, patchBotEnabled, qrImageUrl, type Bot } from "@/lib/api";
import { useToast } from "@/components/ToastProvider";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { IconBadge } from "@/components/ui/IconBadge";
import { Switch } from "@/components/ui/Switch";

interface QrPanelProps {
  initialBot: Bot;
  apiBaseUrl: string;
  /** 5с по умолчанию (FEATURES.md 6.1) — тесты передают меньшее значение
   * вместо фейковых таймеров. */
  pollIntervalMs?: number;
}

export function QrPanel({ initialBot, apiBaseUrl, pollIntervalMs = 5000 }: QrPanelProps) {
  const router = useRouter();
  const { showError, showSuccess } = useToast();
  const [bot, setBot] = useState<Bot>(initialBot);
  const [qrUrl, setQrUrl] = useState<string | null>(null);
  // Раньше "загрузка" считалась законченной, как только появлялся URL
  // картинки (мгновенно) — реальная задержка в 300x300px PNG (пока gateway
  // лениво поднимает Baileys-сессию для бота, который давно не открывали)
  // пряталась за пустым местом без индикатора. Теперь ждём настоящего
  // <img onLoad>, а не просто наличия src. Не сбрасывается на каждой
  // фоновой ротации QR (每 pollIntervalMs) — только на первую загрузку
  // этого монтирования: старая картинка при ротации остаётся видимой, пока
  // не подгрузится новая (обычное поведение <img> при смене src) — сброс
  // здесь давал бы лишнее мигание спиннером каждые pollIntervalMs.
  const [qrImageLoaded, setQrImageLoaded] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const [togglingEnabled, setTogglingEnabled] = useState(false);
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

  const handleToggleEnabled = async () => {
    const next = !bot.enabled;
    setTogglingEnabled(true);
    try {
      const updated = await patchBotEnabled(apiBaseUrl, bot.id, next);
      setBot(updated);
      // Список ботов (BotsTable) рендерится на сервере — без refresh() его
      // бейдж "на паузе" останется устаревшим до жёсткой перезагрузки.
      router.refresh();
    } catch (err) {
      showError(err instanceof Error ? err.message : "Не удалось изменить статус бота");
    } finally {
      setTogglingEnabled(false);
    }
  };

  const enabledBanner = (
    <Banner
      variant={bot.enabled ? "success" : "warning"}
      icon={
        bot.enabled ? (
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
            <circle cx="10" cy="10" r="9" stroke="currentColor" strokeWidth="1.5" />
            <path
              d="M6.5 10.5l2.2 2.2L14 8"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        ) : (
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
            <rect x="6" y="5" width="2.5" height="10" rx="1" fill="currentColor" />
            <rect x="11.5" y="5" width="2.5" height="10" rx="1" fill="currentColor" />
          </svg>
        )
      }
      title={bot.enabled ? "Бот активен — отвечает на сообщения" : "Бот на паузе — не отвечает клиентам"}
      action={
        <Switch
          checked={bot.enabled}
          onChange={() => void handleToggleEnabled()}
          disabled={togglingEnabled}
          aria-label="Бот активен"
        />
      }
    />
  );

  if (bot.linked_at) {
    return (
      <div>
        {enabledBanner}
        <Card className="flex flex-col items-center gap-3 p-8 text-center shadow-elevated">
          <IconBadge variant="success" size="lg">
            <svg width="28" height="28" viewBox="0 0 20 20" fill="none" aria-hidden="true">
              <path
                d="M5 10.5l3.2 3.2L15 6.5"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </IconBadge>
          <div>
            <p className="text-base font-bold text-ink">WhatsApp подключён</p>
            <p className="mt-1 font-mono text-sm text-ink-soft">{bot.phone}</p>
          </div>
          <Button variant="danger" onClick={() => void handleLogout()} disabled={loggingOut}>
            {loggingOut ? "Отключаем…" : "Отключить"}
          </Button>
        </Card>
        {pollError && (
          <p role="alert" className="mt-3 text-sm text-danger">
            {pollError}
          </p>
        )}
      </div>
    );
  }

  return (
    <div>
      {enabledBanner}
      <Card className="p-5 shadow-elevated">
        <p className="text-sm text-ink">Отсканируйте QR в WhatsApp на телефоне</p>
        <div className="relative mt-3 h-[300px] w-[300px]">
          {qrUrl && (
            // eslint-disable-next-line @next/next/no-img-element -- PNG отдаёт api напрямую, не статический ассет Next.js
            <img
              src={qrUrl}
              alt="QR-код для подключения WhatsApp"
              width={300}
              height={300}
              onLoad={() => setQrImageLoaded(true)}
              onError={() => setQrImageLoaded(true)}
              className={`h-[300px] w-[300px] rounded-lg border border-border ${qrImageLoaded ? "" : "invisible"}`}
            />
          )}
          {!qrImageLoaded && (
            <div
              role="status"
              aria-label="Загружаем QR-код"
              className="absolute inset-0 flex items-center justify-center rounded-lg border border-border bg-surface-alt"
            >
              <span className="h-8 w-8 animate-spin rounded-full border-2 border-border border-t-accent" />
            </div>
          )}
        </div>
        {pollError && (
          <p role="alert" className="mt-3 text-sm text-danger">
            {pollError}
          </p>
        )}
      </Card>
    </div>
  );
}
