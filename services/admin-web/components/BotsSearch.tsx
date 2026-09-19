"use client";

import { useMemo, useState } from "react";
import { BotsTable } from "@/components/BotsTable";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import type { Bot } from "@/lib/api";

interface BotsSearchProps {
  bots: Bot[];
}

export function BotsSearch({ bots }: BotsSearchProps) {
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (q === "") return bots;
    return bots.filter(
      (bot) => bot.name.toLowerCase().includes(q) || (bot.phone ?? "").toLowerCase().includes(q),
    );
  }, [bots, query]);

  return (
    <div className="space-y-4">
      {bots.length > 0 && (
        <Input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Поиск по имени или номеру…"
          aria-label="Поиск ботов"
          className="max-w-sm"
        />
      )}
      {filtered.length === 0 && bots.length > 0 ? (
        <EmptyState title="Ничего не найдено" description="Попробуйте другой запрос." />
      ) : (
        <BotsTable bots={filtered} />
      )}
    </div>
  );
}
