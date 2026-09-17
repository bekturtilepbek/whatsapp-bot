export type BotConnectionStatus = "connected" | "pending" | "disconnected";

interface StatusPulseProps {
  status: BotConnectionStatus;
}

interface StatusConfig {
  label: string;
  pillClass: string;
  dotClass: string;
  animated: boolean;
}

const STATUS_CONFIG: Record<BotConnectionStatus, StatusConfig> = {
  connected: {
    label: "Подключён",
    pillClass: "bg-success-soft text-success",
    dotClass: "bg-success",
    animated: true,
  },
  pending: {
    label: "Подключается",
    pillClass: "bg-warning-soft text-warning",
    dotClass: "bg-warning",
    animated: false,
  },
  disconnected: {
    label: "Не подключён",
    pillClass: "bg-surface-alt text-ink-soft",
    dotClass: "bg-ink-faint",
    animated: false,
  },
};

export function StatusPulse({ status }: StatusPulseProps) {
  const config = STATUS_CONFIG[status];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${config.pillClass}`}
    >
      <span className="relative inline-flex h-1.5 w-1.5 rounded-full">
        {config.animated && (
          <span
            className={`absolute inset-0 rounded-full opacity-75 motion-reduce:hidden ${config.dotClass} animate-ping`}
          />
        )}
        <span className={`relative inline-flex h-1.5 w-1.5 rounded-full ${config.dotClass}`} />
      </span>
      {config.label}
    </span>
  );
}
