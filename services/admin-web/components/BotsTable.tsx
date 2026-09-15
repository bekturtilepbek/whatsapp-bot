import Link from "next/link";
import { Badge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/EmptyState";
import { StatusPulse } from "@/components/ui/StatusPulse";
import { Table } from "@/components/ui/Table";
import type { Bot } from "@/lib/api";
import { toConnectionStatus } from "@/lib/botStatus";

interface BotsTableProps {
  bots: Bot[];
}

export function BotsTable({ bots }: BotsTableProps) {
  if (bots.length === 0) {
    return <EmptyState title="Доступа пока нет, обратитесь к владельцу платформы" />;
  }

  return (
    <Table>
      <table>
        <thead>
          <tr>
            <th>Имя</th>
            <th>Статус</th>
            <th>Номер</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {bots.map((bot) => (
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
                <StatusPulse status={toConnectionStatus(bot)} />
              </td>
              <td className="font-mono">{bot.phone ?? "—"}</td>
              <td>
                <Link href={`/bots/${bot.id}`} className="font-medium text-accent hover:underline">
                  Открыть →
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Table>
  );
}
