"use client";

import { useMemo, useState } from "react";
import { BotsTable } from "@/components/BotsTable";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { toConnectionStatus } from "@/lib/botStatus";
import type { Bot } from "@/lib/api";

interface BotsSearchProps {
  bots: Bot[];
}

type StatusFilter = "all" | "connected" | "disconnected";

export function BotsSearch({ bots }: BotsSearchProps) {
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return bots.filter((bot) => {
      const matchesQuery =
        q === "" ||
        bot.name.toLowerCase().includes(q) ||
        (bot.phone ?? "").toLowerCase().includes(q);
      const matchesStatus =
        statusFilter === "all" || toConnectionStatus(bot) === statusFilter;
      return matchesQuery && matchesStatus;
    });
  }, [bots, query, statusFilter]);

  return (
    <div className="space-y-4">
      {bots.length > 0 && (
        <div className="flex flex-wrap items-center gap-3">
          <Input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Поиск по имени или номеру…"
            aria-label="Поиск ботов"
            className="max-w-sm"
          />
          <Select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
            aria-label="Фильтр по статусу подключения"
            className="max-w-[10rem]"
          >
            <option value="all">Все статусы</option>
            <option value="connected">Подключён</option>
            <option value="disconnected">Не подключён</option>
          </Select>
        </div>
      )}
      {filtered.length === 0 && bots.length > 0 ? (
        <EmptyState title="Ничего не найдено" description="Попробуйте другой запрос." />
      ) : (
        <BotsTable bots={filtered} />
      )}
    </div>
  );
}
