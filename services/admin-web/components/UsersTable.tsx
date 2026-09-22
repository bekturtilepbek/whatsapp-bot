"use client";

import { useState, type FormEvent } from "react";
import {
  createUser,
  grantBotAccess,
  patchUser,
  revokeBotAccess,
  type CabinetUser,
  type CabinetUserRole,
} from "@/lib/api";
import type { Bot } from "@/lib/api";
import { useToast } from "@/components/ToastProvider";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Switch } from "@/components/ui/Switch";
import { Table } from "@/components/ui/Table";
import { useInvalidShake } from "@/lib/useInvalidShake";

interface UsersTableProps {
  apiBaseUrl: string;
  users: CabinetUser[];
  bots: Bot[];
}

// superadmin сюда не входит — назначается только bootstrap-скриптом, не
// через кабинет (services/api/src/api/schemas/users.py::AssignableRole).
type AssignableRole = Exclude<CabinetUserRole, "superadmin">;
const ASSIGNABLE_ROLES: { value: AssignableRole; label: string }[] = [
  { value: "admin", label: "Админ" },
  { value: "prompter", label: "Промптер" },
  { value: "client", label: "Клиент" },
];

export function UsersTable({ apiBaseUrl, users, bots }: UsersTableProps) {
  const { showError, showSuccess } = useToast();
  const [rows, setRows] = useState(users);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<AssignableRole>("client");
  const [creating, setCreating] = useState(false);
  const { shake, clear, isInvalid, shakeKey } = useInvalidShake();

  const handleCreate = async (event: FormEvent) => {
    event.preventDefault();
    const invalidFields: string[] = [];
    if (!email.trim()) invalidFields.push("email");
    if (!password.trim()) invalidFields.push("password");
    if (invalidFields.length > 0) {
      showError("Введите email и пароль");
      shake(invalidFields);
      return;
    }
    setCreating(true);
    try {
      const created = await createUser(apiBaseUrl, { email, password, role, bot_ids: [] });
      setRows((current) => [...current, created]);
      setEmail("");
      setPassword("");
      setRole("client");
      showSuccess("Пользователь создан");
    } catch (err) {
      showError(err instanceof Error ? err.message : "Не удалось создать");
    } finally {
      setCreating(false);
    }
  };

  const changeRole = async (userId: string, newRole: AssignableRole) => {
    try {
      const updated = await patchUser(apiBaseUrl, userId, { role: newRole });
      setRows((current) => current.map((u) => (u.id === userId ? updated : u)));
      showSuccess("Роль изменена");
    } catch (err) {
      showError(err instanceof Error ? err.message : "Не удалось изменить роль");
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

  const clientRows = rows.filter((u) => u.role !== "superadmin");

  return (
    <div className="space-y-5">
      <Card className="p-5">
        <h2 className="mb-4 text-[15px] font-semibold text-ink">Новый пользователь</h2>
        <form onSubmit={(event) => void handleCreate(event)} className="flex flex-wrap items-end gap-3">
          <label
            className={`mb-0 block text-sm font-medium ${isInvalid("email") ? "text-danger" : "text-ink"}`}
          >
            <div
              key={isInvalid("email") ? `email-shake-${shakeKey}` : "email"}
              className={isInvalid("email") ? "animate-shake" : undefined}
            >
              Email
              <Input
                type="email"
                value={email}
                onChange={(event) => {
                  setEmail(event.target.value);
                  clear("email");
                }}
                placeholder="client@example.com"
                invalid={isInvalid("email")}
                className="mt-1.5 max-w-xs"
              />
            </div>
          </label>
          <label
            className={`mb-0 block text-sm font-medium ${isInvalid("password") ? "text-danger" : "text-ink"}`}
          >
            <div
              key={isInvalid("password") ? `password-shake-${shakeKey}` : "password"}
              className={isInvalid("password") ? "animate-shake" : undefined}
            >
              Пароль
              <Input
                type="password"
                value={password}
                onChange={(event) => {
                  setPassword(event.target.value);
                  clear("password");
                }}
                placeholder="Пароль"
                invalid={isInvalid("password")}
                className="mt-1.5 max-w-xs"
              />
            </div>
          </label>
          <label className="mb-0 block text-sm font-medium text-ink">
            Роль
            <Select
              value={role}
              onChange={(event) => setRole(event.target.value as AssignableRole)}
              className="mt-1.5"
            >
              {ASSIGNABLE_ROLES.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </Select>
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
                <th>Роль</th>
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
                    <Select
                      value={user.role}
                      onChange={(event) =>
                        void changeRole(user.id, event.target.value as AssignableRole)
                      }
                      aria-label={`Роль: ${user.email}`}
                    >
                      {ASSIGNABLE_ROLES.map((r) => (
                        <option key={r.value} value={r.value}>
                          {r.label}
                        </option>
                      ))}
                    </Select>
                  </td>
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
