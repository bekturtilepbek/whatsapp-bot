import type { Bot } from "@/lib/api";

interface DashboardTableProps {
  bots: Bot[];
}

// Меньше — выше в списке (проблемные боты первыми). "Не подключался"
// (status отсутствует) — не то же самое, что "logged_out": бот мог просто
// ещё не пройти онбординг, это не авария, но и не "здоров" — где-то посередине.
const STATUS_ORDER: Record<string, number> = {
  logged_out: 0,
  reconnecting: 1,
  qr: 2,
  connecting: 3,
  open: 5,
};
const NEVER_LINKED_ORDER = 4;

const STATUS_LABELS: Record<string, string> = {
  open: "🟢 Подключён",
  connecting: "🟡 Подключается",
  qr: "🟡 Ждёт QR-код",
  reconnecting: "🟠 Переподключается",
  logged_out: "🔴 Отключён (logout)",
};
const NEVER_LINKED_LABEL = "⚪ Не подключался";

function statusOrder(status: string | null | undefined): number {
  if (!status) return NEVER_LINKED_ORDER;
  return STATUS_ORDER[status] ?? NEVER_LINKED_ORDER;
}

function statusLabel(status: string | null | undefined): string {
  if (!status) return NEVER_LINKED_LABEL;
  return STATUS_LABELS[status] ?? status;
}

function formatLastSeen(iso: string | null | undefined): string {
  if (!iso) return "—";
  // Строковая операция, не new Date() — иначе разное форматирование на
  // SSR и на клиенте даёт hydration-mismatch (тот же приём, что в
  // AuditLogTable.tsx/PromptEditor.tsx).
  return iso.slice(0, 16).replace("T", " ");
}

export function DashboardTable({ bots }: DashboardTableProps) {
  if (bots.length === 0) {
    return <p>Ботов пока нет</p>;
  }

  const sorted = [...bots].sort((a, b) => {
    const byStatus = statusOrder(a.status) - statusOrder(b.status);
    if (byStatus !== 0) return byStatus;
    return a.name.localeCompare(b.name, "ru");
  });

  return (
    <table>
      <thead>
        <tr>
          <th>Бот</th>
          <th>Статус</th>
          <th>Последняя активность</th>
          <th>Пауза</th>
        </tr>
      </thead>
      <tbody>
        {sorted.map((bot) => (
          <tr key={bot.id}>
            <td>{bot.name}</td>
            <td>{statusLabel(bot.status)}</td>
            <td>{formatLastSeen(bot.last_seen)}</td>
            <td>{bot.enabled ? "—" : "на паузе"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
