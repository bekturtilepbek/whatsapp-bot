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

interface UsersTableProps {
  apiBaseUrl: string;
  users: CabinetUser[];
  bots: Bot[];
}

export function UsersTable({ apiBaseUrl, users, bots }: UsersTableProps) {
  const [rows, setRows] = useState(users);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const handleCreate = async (event: FormEvent) => {
    event.preventDefault();
    if (!email.trim() || !password.trim()) return;
    setError(null);
    setCreating(true);
    try {
      const created = await createUser(apiBaseUrl, { email, password, bot_ids: [] });
      setRows((current) => [...current, created]);
      setEmail("");
      setPassword("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось создать");
    } finally {
      setCreating(false);
    }
  };

  const toggleAccess = async (userId: string, botId: string, hasAccess: boolean) => {
    setError(null);
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
      setError(err instanceof Error ? err.message : "Не удалось изменить доступ");
    }
  };

  const toggleActive = async (userId: string, isActive: boolean) => {
    setError(null);
    try {
      await patchUser(apiBaseUrl, userId, { is_active: !isActive });
      setRows((current) =>
        current.map((u) => (u.id === userId ? { ...u, is_active: !isActive } : u)),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось изменить статус");
    }
  };

  return (
    <>
      {error && (
        <p role="alert" style={{ color: "crimson" }}>
          {error}
        </p>
      )}
      <form onSubmit={(event) => void handleCreate(event)}>
        <input
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          placeholder="client@example.com"
          aria-label="Email"
        />
        <input
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          placeholder="Пароль"
          aria-label="Пароль"
        />
        <button type="submit" disabled={creating}>
          {creating ? "Создаём…" : "Создать пользователя"}
        </button>
      </form>
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
          {rows
            .filter((u) => !u.is_platform_owner)
            .map((user) => (
              <tr key={user.id}>
                <td>{user.email}</td>
                <td>
                  <input
                    type="checkbox"
                    checked={user.is_active}
                    onChange={() => void toggleActive(user.id, user.is_active)}
                    aria-label={`Активен: ${user.email}`}
                  />
                </td>
                {bots.map((bot) => {
                  const hasAccess = user.bot_ids.includes(bot.id);
                  return (
                    <td key={bot.id}>
                      <input
                        type="checkbox"
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
    </>
  );
}
