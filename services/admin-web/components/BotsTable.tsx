"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import type { MouseEvent } from "react";
import { Badge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/EmptyState";
import { StatusPulse } from "@/components/ui/StatusPulse";
import { Table } from "@/components/ui/Table";
import type { Bot } from "@/lib/api";
import { toConnectionStatus } from "@/lib/botStatus";
import { LIFECYCLE_STATUS_BADGES } from "@/lib/lifecycleStatus";

interface BotsTableProps {
  bots: Bot[];
}

export function BotsTable({ bots }: BotsTableProps) {
  const router = useRouter();

  if (bots.length === 0) {
    return <EmptyState title="Доступа пока нет, обратитесь к владельцу платформы" />;
  }

  // Клик по любой ячейке строки открывает бота (2026-09-30). Ссылка "Открыть"
  // остаётся — для клавиатуры, скринридеров и открытия в новой вкладке; клик
  // по самой ссылке отдаём ей, чтобы не навигировать дважды.
  function openRow(event: MouseEvent<HTMLTableRowElement>, botId: string): void {
    if ((event.target as HTMLElement).closest("a")) return;
    router.push(`/bots/${botId}`);
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
            <tr
              key={bot.id}
              onClick={(event) => openRow(event, bot.id)}
              className="cursor-pointer transition-colors hover:bg-surface-alt"
            >
              <td>
                {bot.name}
                {bot.lifecycle_status && (
                  <Badge
                    variant={LIFECYCLE_STATUS_BADGES[bot.lifecycle_status].variant}
                    className="ml-2"
                  >
                    {LIFECYCLE_STATUS_BADGES[bot.lifecycle_status].label}
                  </Badge>
                )}
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
                  Открыть
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Table>
  );
}
