import { Badge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/EmptyState";
import { StatusPulse } from "@/components/ui/StatusPulse";
import { Table } from "@/components/ui/Table";
import type { Bot } from "@/lib/api";
import { toConnectionStatus } from "@/lib/botStatus";

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

function statusOrder(status: string | null | undefined): number {
  if (!status) return NEVER_LINKED_ORDER;
  return STATUS_ORDER[status] ?? NEVER_LINKED_ORDER;
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
    return <EmptyState title="Ботов пока нет" />;
  }

  const sorted = [...bots].sort((a, b) => {
    const byStatus = statusOrder(a.status) - statusOrder(b.status);
    if (byStatus !== 0) return byStatus;
    return a.name.localeCompare(b.name, "ru");
  });

  return (
    <Table>
      <table>
        <thead>
          <tr>
            <th>Бот</th>
            <th>Статус</th>
            <th>Последняя активность</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((bot) => (
            <tr key={bot.id}>
              <td>
                {bot.name}
                {!bot.enabled && (
                  <Badge variant="paused" className="ml-2">
                    на паузе
                  </Badge>
                )}
              </td>
              <td>
                <div className="flex items-center gap-2">
                  <StatusPulse status={toConnectionStatus(bot)} />
                  {bot.status && bot.status !== "open" && (
                    <span className="font-mono text-xs text-ink-soft">{bot.status}</span>
                  )}
                </div>
              </td>
              <td className="font-mono">{formatLastSeen(bot.last_seen)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Table>
  );
}
