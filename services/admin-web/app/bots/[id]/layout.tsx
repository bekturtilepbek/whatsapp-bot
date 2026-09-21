import type { ReactNode } from "react";
import { notFound } from "next/navigation";
import { StatusPulse } from "@/components/ui/StatusPulse";
import { Tabs } from "@/components/ui/Tabs";
import { TabLink } from "@/components/ui/TabLink";
import { fetchBot } from "@/lib/api";
import { toConnectionStatus } from "@/lib/botStatus";
import { currentUserIsOwner } from "@/lib/currentUser";
import { API_INTERNAL_URL } from "@/lib/env";

export default async function BotLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const [bot, isOwner] = await Promise.all([fetchBot(API_INTERNAL_URL, id), currentUserIsOwner()]);
  if (!bot) {
    notFound();
  }

  return (
    <div>
      <div className="mb-6">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold text-ink">{bot.name}</h1>
          <StatusPulse status={toConnectionStatus(bot)} />
        </div>
        {bot.phone && <p className="mt-1 font-mono text-sm text-ink-soft">{bot.phone}</p>}
      </div>

      <Tabs ariaLabel="Разделы бота">
        <TabLink href={`/bots/${bot.id}`}>Обзор</TabLink>
        <TabLink href={`/bots/${bot.id}/prompts`} exact={false}>
          Промпты
        </TabLink>
        <TabLink href={`/bots/${bot.id}/products`} exact={false}>
          Товары
        </TabLink>
        <TabLink href={`/bots/${bot.id}/settings`} exact={false}>
          Настройки
        </TabLink>
        <TabLink href={`/bots/${bot.id}/documents`} exact={false}>
          Документы
        </TabLink>
        <TabLink href={`/bots/${bot.id}/blocked-numbers`} exact={false}>
          Чёрный список
        </TabLink>
        <TabLink href={`/bots/${bot.id}/chats`} exact={false}>
          Активные чаты
        </TabLink>
        {isOwner && (
          <TabLink href={`/bots/${bot.id}/sandbox`} exact={false}>
            Песочница
          </TabLink>
        )}
      </Tabs>

      {children}
    </div>
  );
}
