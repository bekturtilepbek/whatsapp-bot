"use client";

import { useState, type FormEvent } from "react";
import {
  createUser,
  grantBotAccess,
  patchUser,
  revokeBotAccess,
  type CabinetUser,
} from "@/lib/api";
import type { Bot } from "@/lib/api";
import { useToast } from "@/components/ToastProvider";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Switch } from "@/components/ui/Switch";
import { Table } from "@/components/ui/Table";

interface UsersTableProps {
  apiBaseUrl: string;
  users: CabinetUser[];
  bots: Bot[];
}

export function UsersTable({ apiBaseUrl, users, bots }: UsersTableProps) {
  const { showError, showSuccess } = useToast();
  const [rows, setRows] = useState(users);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [creating, setCreating] = useState(false);

  const handleCreate = async (event: FormEvent) => {
    event.preventDefault();
    if (!email.trim() || !password.trim()) return;
    setCreating(true);
    try {
      const created = await createUser(apiBaseUrl, { email, password, bot_ids: [] });
      setRows((current) => [...current, created]);
      setEmail("");
      setPassword("");
      showSuccess("Пользователь создан");
    } catch (err) {
      showError(err instanceof Error ? err.message : "Не удалось создать");
    } finally {
      setCreating(false);
    }
  };

  // toggleAccess/toggleActive — чекбоксы: сама смена состояния чекбокса уже
  // видимое подтверждение успеха, отдельный toast был бы шумом на каждый
  // клик. Ошибка — другое дело, без неё непонятно, почему чекбокс не
  // изменился (состояние не обновляется при catch).
  const toggleAccess = async (userId: string, botId: string, hasAccess: boolean) => {
    try {
      if (hasAccess) {
        await revokeBotAccess(apiBaseUrl, userId, botId);
      } else {
        await grantBotAccess(apiBaseUrl, userId, botId);
      }
      setRows((current) =>
        current.map((u) =>
          u.id === userId
            ? {
                ...u,
                bot_ids: hasAccess ? u.bot_ids.filter((id) => id !== botId) : [...u.bot_ids, botId],
              }
            : u,
        ),
      );
    } catch (err) {
      showError(err instanceof Error ? err.message : "Не удалось изменить доступ");
    }
  };

  const toggleActive = async (userId: string, isActive: boolean) => {
    try {
      await patchUser(apiBaseUrl, userId, { is_active: !isActive });
      setRows((current) =>
        current.map((u) => (u.id === userId ? { ...u, is_active: !isActive } : u)),
      );
    } catch (err) {
      showError(err instanceof Error ? err.message : "Не удалось изменить статус");
    }
  };

  const clientRows = rows.filter((u) => !u.is_platform_owner);

  return (
    <div className="space-y-5">
      <Card className="p-5">
        <h2 className="mb-4 text-[15px] font-semibold text-ink">Новый пользователь</h2>
        <form onSubmit={(event) => void handleCreate(event)} className="flex flex-wrap items-end gap-3">
          <label className="mb-0 block text-sm font-medium text-ink">
            Email
            <Input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="client@example.com"
              className="mt-1.5 max-w-xs"
            />
          </label>
          <label className="mb-0 block text-sm font-medium text-ink">
            Пароль
            <Input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="Пароль"
              className="mt-1.5 max-w-xs"
            />
          </label>
          <Button type="submit" disabled={creating}>
            {creating ? "Создаём…" : "Создать пользователя"}
          </Button>
        </form>
      </Card>

      {clientRows.length === 0 ? (
        <EmptyState
          title="Пользователей пока нет"
          description="Создайте первого клиента формой выше, затем выдайте доступ к нужным ботам."
        />
      ) : (
        <Table>
          <table>
            <thead>
              <tr>
                <th>Email</th>
                <th>Активен</th>
                {bots.map((bot) => (
                  <th key={bot.id}>{bot.name}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {clientRows.map((user) => (
                <tr key={user.id}>
                  <td>{user.email}</td>
                  <td>
                    <Switch
                      checked={user.is_active}
                      onChange={() => void toggleActive(user.id, user.is_active)}
                      aria-label={`Активен: ${user.email}`}
                    />
                  </td>
                  {bots.map((bot) => {
                    const hasAccess = user.bot_ids.includes(bot.id);
                    return (
                      <td key={bot.id}>
                        <Switch
                          checked={hasAccess}
                          onChange={() => void toggleAccess(user.id, bot.id, hasAccess)}
                          aria-label={`${bot.name}: ${user.email}`}
                        />
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </Table>
      )}
    </div>
  );
}
