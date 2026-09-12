export type BotConnectionStatus = "connected" | "pending" | "disconnected";

interface StatusPulseProps {
  status: BotConnectionStatus;
}

interface StatusConfig {
  label: string;
  dotClass: string;
  labelClass: string;
  animated: boolean;
}

const STATUS_CONFIG: Record<BotConnectionStatus, StatusConfig> = {
  connected: { label: "Подключён", dotClass: "bg-success", labelClass: "text-success", animated: true },
  pending: { label: "Ждёт QR", dotClass: "bg-warning", labelClass: "text-warning", animated: false },
  disconnected: {
    label: "Не подключён",
    dotClass: "bg-ink-faint",
    labelClass: "text-ink-soft",
    animated: false,
  },
};

export function StatusPulse({ status }: StatusPulseProps) {
  const config = STATUS_CONFIG[status];
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span className={`relative inline-flex h-2 w-2 rounded-full ${config.dotClass}`}>
        {config.animated && (
          <span
            className={`absolute -inset-1 rounded-full opacity-60 motion-reduce:hidden ${config.dotClass} animate-ping`}
          />
        )}
      </span>
      <span className={config.labelClass}>{config.label}</span>
    </span>
  );
}
