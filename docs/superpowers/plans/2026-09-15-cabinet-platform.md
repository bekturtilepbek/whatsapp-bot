# Cabinet Redesign — Platform Screens Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the four owner-only platform screens — `/dashboard`
(`DashboardTable`), `/users` (`UsersTable`), `/audit-log` (`AuditLogTable`),
`/usage` (`UsageTable`) — onto the `components/ui/` design system. The
eighth screen-group wave. No new primitives, no business-logic changes
(with one narrow, deliberate exception in Task 1 — see below).

**Architecture:** Unlike every bot-scoped screen migrated so far, these
four routes sit OUTSIDE `app/bots/[id]/layout.tsx` — there is no shared
chrome already rendering a heading. Each page therefore gets its own
`PageHeader` (existing primitive, already used at `/bots` and `/bots/new`
— the only other top-level, non-bot-scoped routes migrated so far), not a
dropped `<h1>`.

Each of the four components is independent (different file, different
page, no shared interface between them beyond primitives both already use),
so this plan is four tasks, one per screen.

**The one deliberate exception (Task 1, `DashboardTable`):** the spec calls
for reusing `StatusPulse` (`connected`/`pending`/`disconnected`) on the
dashboard for visual consistency with the bots list and bot card header.
But the dashboard's whole purpose (FEATURES.md 6.17) is surfacing problem
bots first, and `StatusPulse`'s 3-state model collapses `logged_out` (a
real outage — a session existed and dropped) and "never linked" (normal —
a bot just hasn't been onboarded yet) into the same "Не подключён" label,
losing exactly the distinction an ops screen needs. Resolved with the
human partner: keep `StatusPulse` for the at-a-glance color/consistency,
and add a small `font-mono` caption underneath showing the raw
`bot.status` value verbatim — but only for non-`"open"` statuses (a
healthy bot's caption would just repeat "open" under "Подключён", adding
noise for the common case with no diagnostic value). The row `sort`
order — the actual "problem bots first" logic — is untouched; only the
display gains the caption. This is presentational (a caption added next
to an existing value), not a new business rule.

Also in Task 1: the separate "Пауза" column merges into the "Бот" column
as an inline `Badge`, exactly matching `BotsTable.tsx`'s existing
convention for the same information (both tables show overlapping bot
lists and should read as one visual language) — 4 columns become 3, no
information is dropped.

**AuditLogTable's and UsageTable's inline error display is NOT converted
to the toast system.** Both currently hold their fetch error in local
`useState` and render it as `<p role="alert" style={{color:"crimson"}}>` —
restyle this with tokens (`text-sm text-danger`) but keep the inline
`useState`/`role="alert"` mechanism exactly as-is. Switching to
`useToast()` would be a real behavior change (auto-hide timing, error
persisting next to the filter vs. vanishing after 6-8s) outside a styling
wave's mandate — the same reasoning that kept `QrPanel`'s live-poll banner
inline instead of toast (FEATURES.md 6.5).

**Tech Stack:** Next.js 15 (App Router, React 19 Server Components),
Tailwind CSS v4 + `components/ui/` primitives (already in `dev`), vitest +
@testing-library/react.

**Spec:** `docs/superpowers/specs/2026-09-13-cabinet-redesign-design.md`
(screen-group 9: "Платформенный раздел (owner-only)")

## Global Constraints

- **Tokens are the only source of color/font values.**
- **Every `<label>` gets an explicit `mb-0`**, spacing rhythm comes from
  `space-y-*`/`gap-*` on a wrapping element.
- **No redundant `aria-label`.** A field only gets `aria-label` when its
  accessible name isn't already supplied by a wrapping `<label>`'s visible
  text, or when that text differs from what the label should announce
  (e.g. `AuditLogTable`'s filter: visible label "Бот", `aria-label="Фильтр
  по боту"` — different strings, both kept, not redundant).
- **Existing tests are the regression contract.** Each component's test
  file gets at most one new test appended for genuinely new
  behavior (an `EmptyState` that didn't exist before); everything else
  stays verbatim. `DashboardTable.test.tsx` is the one exception — two
  existing tests assert on exact visible text (the emoji-prefixed status
  labels) that this migration deliberately removes; those two are rewritten
  to assert the new text, not deleted or reinterpreted.
- **Every route supplies its own single `<main>`.**
- **No duplicate call-to-action.**
- Conventional Commits; each task commits its own working, tested slice.

---

### Task 1: `DashboardTable` + `/dashboard` page

**Files:**
- Modify: `services/admin-web/components/DashboardTable.tsx`
- Modify: `services/admin-web/components/DashboardTable.test.tsx`
- Modify: `services/admin-web/app/dashboard/page.tsx`

**Interfaces:**
- Consumes: `Badge`, `EmptyState`, `StatusPulse`, `Table` (existing
  primitives), `toConnectionStatus` from `lib/botStatus.ts` (existing
  shared helper — do not reimplement the connected/pending/disconnected
  mapping locally).

- [ ] **Step 1: Update `DashboardTable.test.tsx` — two tests rewritten, one added, three untouched**

Replace the full content of `services/admin-web/components/DashboardTable.test.tsx`:

```tsx
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { DashboardTable } from "@/components/DashboardTable";
import type { Bot } from "@/lib/api";

function makeBot(overrides: Partial<Bot>): Bot {
  return {
    id: "1",
    name: "Бот",
    enabled: true,
    phone: null,
    linked_at: null,
    system_prompt: "промпт",
    image_prompt: null,
    pdf_prompt: null,
    status: null,
    last_seen: null,
    ...overrides,
  };
}

describe("DashboardTable", () => {
  it("shows an explanatory message instead of a table when there are no bots", () => {
    render(<DashboardTable bots={[]} />);
    expect(screen.getByText("Ботов пока нет")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("renders the StatusPulse label and last_seen for a healthy bot, with no raw-status caption", () => {
    render(
      <DashboardTable
        bots={[
          makeBot({ id: "1", name: "Открыт", status: "open", last_seen: "2026-09-12T10:30:00Z" }),
        ]}
      />
    );
    expect(screen.getByText("Подключён")).toBeInTheDocument();
    expect(screen.getByText("2026-09-12 10:30")).toBeInTheDocument();
    // "open" не дублируется мелкой подписью — для здорового бота это шум,
    // подпись нужна только там, где StatusPulse что-то схлопывает.
    expect(screen.queryByText("open")).not.toBeInTheDocument();
  });

  it("shows a placeholder for a bot that was never linked, with no raw-status caption", () => {
    render(<DashboardTable bots={[makeBot({ status: null, last_seen: null })]} />);
    expect(screen.getByText("Не подключён")).toBeInTheDocument();
    // "—" встречается один раз в этой строке (последняя активность) — колонка
    // "Пауза" ушла, бейдж "на паузе" не рендерится для enabled:true.
    expect(screen.getAllByText("—")).toHaveLength(1);
  });

  it("shows the raw status as a caption for a bot with a problem status", () => {
    render(<DashboardTable bots={[makeBot({ status: "reconnecting" })]} />);
    expect(screen.getByText("Подключается")).toBeInTheDocument();
    expect(screen.getByText("reconnecting")).toBeInTheDocument();
  });

  it("marks a paused bot", () => {
    render(<DashboardTable bots={[makeBot({ enabled: false })]} />);
    expect(screen.getByText("на паузе")).toBeInTheDocument();
  });

  // FEATURES.md 6.17 — операционное здоровье: проблемные боты должны быть
  // видны сразу, не потеряны в алфавитном списке из 31 бота.
  it("sorts problem bots (not open) before healthy ones, regardless of name", () => {
    render(
      <DashboardTable
        bots={[
          makeBot({ id: "1", name: "А-бот, всё хорошо", status: "open" }),
          makeBot({ id: "2", name: "Я-бот, разорвана сессия", status: "logged_out" }),
          makeBot({ id: "3", name: "Б-бот, переподключается", status: "reconnecting" }),
        ]}
      />
    );
    const rows = screen.getAllByRole("row").slice(1); // без заголовка
    const names = rows.map((r) => r.textContent);
    expect(names[0]).toContain("Я-бот, разорвана сессия");
    expect(names[1]).toContain("Б-бот, переподключается");
    expect(names[2]).toContain("А-бот, всё хорошо");
  });
});
```

(Diff from the original: test 2 renamed and now asserts `"Подключён"` +
absence of an `"open"` caption instead of `"🟢 Подключён"`; test 3 renamed
and now asserts `"Не подключён"` + exactly one `"—"` instead of
`"⚪ Не подключался"` + two `"—"`; one new test asserting the raw-status
caption for a problem bot; the paused-bot and sort-order tests are
byte-identical to the original.)

- [ ] **Step 2: Run the test file to verify it fails against the current component**

Run: `npx vitest run components/DashboardTable.test.tsx`
Expected: 4 of 6 tests FAIL (the two rewritten ones plus the new
raw-status-caption one) against the current emoji-label implementation;
the paused-bot and sort-order tests still PASS (their assertions didn't
change).

- [ ] **Step 3: Rewrite `DashboardTable.tsx`**

Replace the full content of `services/admin-web/components/DashboardTable.tsx`:

```tsx
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
                    <span className="font-mono text-xs text-ink-faint">{bot.status}</span>
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
```

- [ ] **Step 4: Run the test file to verify all 6 cases pass**

Run: `npx vitest run components/DashboardTable.test.tsx`
Expected: PASS (6 tests).

- [ ] **Step 5: Rewrite `app/dashboard/page.tsx`**

Replace the full content of `services/admin-web/app/dashboard/page.tsx`:

```tsx
import { redirect } from "next/navigation";
import { DashboardTable } from "@/components/DashboardTable";
import { PageHeader } from "@/components/ui/PageHeader";
import { fetchBots } from "@/lib/api";
import { currentUserIsOwner } from "@/lib/currentUser";
import { API_INTERNAL_URL } from "@/lib/env";

export default async function DashboardPage() {
  if (!(await currentUserIsOwner())) {
    redirect("/bots");
  }

  const bots = await fetchBots(API_INTERNAL_URL);

  return (
    <main>
      <PageHeader title="Дашборд" subtitle={`Ботов: ${bots.length}`} />
      <DashboardTable bots={bots} />
    </main>
  );
}
```

- [ ] **Step 6: Run the full suite, typecheck and the build**

Run: `npm test`
Expected: full existing suite passes.

Run: `npx tsc --noEmit`
Expected: clean.

Run: `npm run build`
Expected: build succeeds.

- [ ] **Step 7: Commit**

```bash
git add services/admin-web/components/DashboardTable.tsx services/admin-web/components/DashboardTable.test.tsx \
  services/admin-web/app/dashboard/page.tsx
git commit -m "feat(admin-web): migrate DashboardTable and its page to the design system"
```

---

### Task 2: `UsersTable` + `/users` page

**Files:**
- Modify: `services/admin-web/components/UsersTable.tsx`
- Modify: `services/admin-web/components/UsersTable.test.tsx` (append one
  test only)
- Modify: `services/admin-web/app/users/page.tsx`

**Interfaces:**
- Consumes: `Button`, `Card`, `EmptyState`, `Input`, `Switch`, `Table`
  (existing primitives).

- [ ] **Step 1: Add the one new test case to `UsersTable.test.tsx` (every existing case stays untouched)**

Append to the end of `services/admin-web/components/UsersTable.test.tsx`:

```tsx
it("shows an empty state when there are no non-owner users", () => {
  render(<UsersTable apiBaseUrl="http://api" users={[owner]} bots={bots} />);
  expect(screen.getByText("Пользователей пока нет")).toBeInTheDocument();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run the test file to verify the new case fails**

Run: `npx vitest run components/UsersTable.test.tsx`
Expected: the 9 pre-existing tests PASS, the new one FAILS — the current
component always renders a `<table>` (with an empty `<tbody>` when there
are no non-owner users), it never renders "Пользователей пока нет".

- [ ] **Step 3: Rewrite `UsersTable.tsx`**

Replace the full content of `services/admin-web/components/UsersTable.tsx`:

```tsx
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
```

- [ ] **Step 4: Run the test file to verify all 10 cases pass**

Run: `npx vitest run components/UsersTable.test.tsx`
Expected: PASS (10 tests — the original 9 plus the new empty-state case).
Every existing test keeps passing unchanged: `getByLabelText("Email")`/
`getByLabelText("Пароль")` still resolve (implicit association via the
wrapping `<label>`'s visible text, same strings as the old `aria-label`
values); `Switch` is still a real `<input type="checkbox">` forwarding
`aria-label`/`checked`/`onChange`, so every `getByLabelText("Bot Two:
client1@example.com")`-style query and `.checked` assertion is unaffected.

- [ ] **Step 5: Rewrite `app/users/page.tsx`**

Replace the full content of `services/admin-web/app/users/page.tsx`:

```tsx
import { redirect } from "next/navigation";
import { UsersTable } from "@/components/UsersTable";
import { PageHeader } from "@/components/ui/PageHeader";
import { fetchBots, fetchUsers } from "@/lib/api";
import { currentUserIsOwner } from "@/lib/currentUser";
import { API_INTERNAL_URL, API_PROXY_PATH } from "@/lib/env";

export default async function UsersPage() {
  if (!(await currentUserIsOwner())) {
    redirect("/bots");
  }

  const [users, bots] = await Promise.all([
    fetchUsers(API_INTERNAL_URL),
    fetchBots(API_INTERNAL_URL),
  ]);
  const clientCount = users.filter((u) => !u.is_platform_owner).length;

  return (
    <main>
      <PageHeader title="Пользователи" subtitle={`Пользователей: ${clientCount}`} />
      <UsersTable apiBaseUrl={API_PROXY_PATH} users={users} bots={bots} />
    </main>
  );
}
```

- [ ] **Step 6: Run the full suite, typecheck and the build**

Run: `npm test`
Expected: full existing suite passes.

Run: `npx tsc --noEmit`
Expected: clean.

Run: `npm run build`
Expected: build succeeds.

- [ ] **Step 7: Commit**

```bash
git add services/admin-web/components/UsersTable.tsx services/admin-web/components/UsersTable.test.tsx \
  services/admin-web/app/users/page.tsx
git commit -m "feat(admin-web): migrate UsersTable and its page to the design system"
```

---

### Task 3: `AuditLogTable` + `/audit-log` page

**Files:**
- Modify: `services/admin-web/components/AuditLogTable.tsx`
- Modify: `services/admin-web/components/AuditLogTable.test.tsx` (append
  one test only)
- Modify: `services/admin-web/app/audit-log/page.tsx`

**Interfaces:**
- Consumes: `Button`, `EmptyState`, `Select`, `Table` (existing
  primitives).

- [ ] **Step 1: Add the one new test case to `AuditLogTable.test.tsx` (every existing case stays untouched)**

Append to the end of `services/admin-web/components/AuditLogTable.test.tsx`:

```tsx
it("shows an empty state when there are no entries", () => {
  render(<AuditLogTable apiBaseUrl="http://api" entries={[]} bots={bots} pageSize={50} />);
  expect(screen.getByText("Записей аудит-лога пока нет")).toBeInTheDocument();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run the test file to verify the new case fails**

Run: `npx vitest run components/AuditLogTable.test.tsx`
Expected: the 7 pre-existing tests PASS, the new one FAILS — the current
component renders an empty `<table>` for a zero-length entries list, not
an empty state.

- [ ] **Step 3: Rewrite `AuditLogTable.tsx`**

Replace the full content of `services/admin-web/components/AuditLogTable.tsx`:

```tsx
"use client";

import { useState } from "react";
import { fetchAuditLog, type AuditLogEntry, type Bot } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Select } from "@/components/ui/Select";
import { Table } from "@/components/ui/Table";

interface AuditLogTableProps {
  apiBaseUrl: string;
  entries: AuditLogEntry[];
  bots: Bot[];
  /** Совпадает с лимитом, которым страница делала первый fetchAuditLog —
   * тот же приём, что в BlockedNumbersTable/ProductsTable: пришло МЕНЬШЕ
   * pageSize — дальше грузить нечего. */
  pageSize: number;
}

function formatTimestamp(iso: string): string {
  // Чистая строковая операция, не new Date() — иначе разное форматирование
  // на SSR и на клиенте даёт hydration-mismatch (тот же урок, что в
  // PromptEditor.tsx).
  return iso.slice(0, 16).replace("T", " ");
}

export function AuditLogTable({ apiBaseUrl, entries, bots, pageSize }: AuditLogTableProps) {
  const [rows, setRows] = useState(entries);
  const [botFilter, setBotFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const [hasMore, setHasMore] = useState(entries.length === pageSize);
  const [error, setError] = useState<string | null>(null);

  const handleFilterChange = async (nextBotId: string) => {
    setBotFilter(nextBotId);
    setError(null);
    setLoading(true);
    try {
      const next = await fetchAuditLog(apiBaseUrl, {
        botId: nextBotId || undefined,
        limit: pageSize,
      });
      setRows(next);
      setHasMore(next.length === pageSize);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить лог");
    } finally {
      setLoading(false);
    }
  };

  const handleLoadMore = async () => {
    setError(null);
    setLoading(true);
    try {
      const next = await fetchAuditLog(apiBaseUrl, {
        botId: botFilter || undefined,
        limit: pageSize,
        offset: rows.length,
      });
      setRows((current) => [...current, ...next]);
      setHasMore(next.length === pageSize);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить ещё");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-5">
      <label className="mb-0 block max-w-xs text-sm font-medium text-ink">
        Бот
        <Select
          value={botFilter}
          onChange={(e) => void handleFilterChange(e.target.value)}
          aria-label="Фильтр по боту"
          className="mt-1.5"
        >
          <option value="">Все боты</option>
          {bots.map((bot) => (
            <option key={bot.id} value={bot.id}>
              {bot.name}
            </option>
          ))}
        </Select>
      </label>

      {error && <p role="alert" className="text-sm text-danger">{error}</p>}

      {rows.length === 0 ? (
        <EmptyState title="Записей аудит-лога пока нет" />
      ) : (
        <>
          <Table>
            <table>
              <thead>
                <tr>
                  <th>Время (UTC)</th>
                  <th>Кто</th>
                  <th>Бот</th>
                  <th>Действие</th>
                  <th>Payload</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((entry) => (
                  <tr key={entry.id}>
                    <td className="font-mono">{formatTimestamp(entry.created_at)}</td>
                    <td>{entry.actor_email}</td>
                    <td>{entry.bot_name ?? "—"}</td>
                    <td>
                      <code className="font-mono text-xs">{entry.action}</code>
                    </td>
                    <td>
                      {entry.payload && (
                        <details>
                          <summary className="cursor-pointer text-sm text-accent">показать</summary>
                          <pre className="mt-1.5 max-w-md overflow-x-auto rounded-md bg-surface-alt p-2 text-xs">
                            {JSON.stringify(entry.payload, null, 2)}
                          </pre>
                        </details>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Table>
          {hasMore && (
            <Button variant="secondary" onClick={() => void handleLoadMore()} disabled={loading}>
              {loading ? "Загружаем…" : "Показать ещё"}
            </Button>
          )}
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run the test file to verify all 8 cases pass**

Run: `npx vitest run components/AuditLogTable.test.tsx`
Expected: PASS (8 tests — the original 7 plus the new empty-state case).

- [ ] **Step 5: Rewrite `app/audit-log/page.tsx`**

Replace the full content of `services/admin-web/app/audit-log/page.tsx`:

```tsx
import { redirect } from "next/navigation";
import { AuditLogTable } from "@/components/AuditLogTable";
import { PageHeader } from "@/components/ui/PageHeader";
import { fetchAuditLog, fetchBots } from "@/lib/api";
import { currentUserIsOwner } from "@/lib/currentUser";
import { API_INTERNAL_URL, API_PROXY_PATH } from "@/lib/env";

const AUDIT_LOG_PAGE_SIZE = 50;

export default async function AuditLogPage() {
  if (!(await currentUserIsOwner())) {
    redirect("/bots");
  }

  const [entries, bots] = await Promise.all([
    fetchAuditLog(API_INTERNAL_URL, { limit: AUDIT_LOG_PAGE_SIZE }),
    fetchBots(API_INTERNAL_URL),
  ]);

  return (
    <main>
      <PageHeader title="Аудит-лог" />
      <AuditLogTable
        apiBaseUrl={API_PROXY_PATH}
        entries={entries}
        bots={bots}
        pageSize={AUDIT_LOG_PAGE_SIZE}
      />
    </main>
  );
}
```

- [ ] **Step 6: Run the full suite, typecheck and the build**

Run: `npm test`
Expected: full existing suite passes.

Run: `npx tsc --noEmit`
Expected: clean.

Run: `npm run build`
Expected: build succeeds.

- [ ] **Step 7: Commit**

```bash
git add services/admin-web/components/AuditLogTable.tsx services/admin-web/components/AuditLogTable.test.tsx \
  services/admin-web/app/audit-log/page.tsx
git commit -m "feat(admin-web): migrate AuditLogTable and its page to the design system"
```

---

### Task 4: `UsageTable` + `/usage` page

**Files:**
- Modify: `services/admin-web/components/UsageTable.tsx`
- Modify: `services/admin-web/app/usage/page.tsx`

**Interfaces:**
- Consumes: `Select`, `Table` (existing primitives).

No test changes in this task — `UsageTable`'s zero-rows behavior is
already correct and already tested (`"renders an empty totals row when
there is no usage"`): unlike every other table in this series, an empty
`UsageTable` deliberately still renders the table with a zeroed `Итого`
row, not an `EmptyState` — the zero itself is the answer to "did this bot
cost anything this period," and hiding the table would hide that answer.
This migration must preserve that shape exactly.

- [ ] **Step 1: Rewrite `UsageTable.tsx`**

Replace the full content of `services/admin-web/components/UsageTable.tsx`:

```tsx
"use client";

import { useState } from "react";
import { fetchUsage, type UsagePeriod, type UsageSummary } from "@/lib/api";
import { Select } from "@/components/ui/Select";
import { Table } from "@/components/ui/Table";

interface UsageTableProps {
  apiBaseUrl: string;
  summaries: UsageSummary[];
  initialPeriod: UsagePeriod;
}

const PERIOD_LABELS: Record<UsagePeriod, string> = {
  "7d": "7 дней",
  "30d": "30 дней",
  "90d": "90 дней",
  all: "Всё время",
};

function formatCost(cost: string): string {
  // cost — Decimal-строка с бэкенда (см. lib/api.ts) — форматируем как
  // обычное число, точность JS float здесь не критична: экран показывает
  // ОЦЕНКУ, не биллинговые данные (см. подпись под таблицей).
  return Number(cost).toFixed(4);
}

export function UsageTable({ apiBaseUrl, summaries, initialPeriod }: UsageTableProps) {
  const [rows, setRows] = useState(summaries);
  const [period, setPeriod] = useState(initialPeriod);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handlePeriodChange = async (nextPeriod: UsagePeriod) => {
    setPeriod(nextPeriod);
    setError(null);
    setLoading(true);
    try {
      const next = await fetchUsage(apiBaseUrl, nextPeriod);
      setRows(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить расходы");
    } finally {
      setLoading(false);
    }
  };

  const totalTokensIn = rows.reduce((sum, r) => sum + r.tokens_in, 0);
  const totalTokensOut = rows.reduce((sum, r) => sum + r.tokens_out, 0);
  const totalCost = rows.reduce((sum, r) => sum + Number(r.cost), 0);

  return (
    <div className="space-y-5">
      <label className="mb-0 block max-w-xs text-sm font-medium text-ink">
        Период
        <Select
          value={period}
          onChange={(e) => void handlePeriodChange(e.target.value as UsagePeriod)}
          aria-label="Период"
          className="mt-1.5"
        >
          {(Object.keys(PERIOD_LABELS) as UsagePeriod[]).map((p) => (
            <option key={p} value={p}>
              {PERIOD_LABELS[p]}
            </option>
          ))}
        </Select>
      </label>

      {loading && <p className="text-sm text-ink-soft">Загружаем…</p>}
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}

      <Table>
        <table>
          <thead>
            <tr>
              <th>Бот</th>
              <th>Токены (вход)</th>
              <th>Токены (выход)</th>
              <th>Стоимость ($)</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.bot_id}>
                <td>{row.bot_name}</td>
                <td className="font-mono">{row.tokens_in.toLocaleString("ru-RU")}</td>
                <td className="font-mono">{row.tokens_out.toLocaleString("ru-RU")}</td>
                <td className="font-mono">{formatCost(row.cost)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td className="font-semibold">Итого</td>
              <td className="font-mono font-semibold">{totalTokensIn.toLocaleString("ru-RU")}</td>
              <td className="font-mono font-semibold">{totalTokensOut.toLocaleString("ru-RU")}</td>
              <td className="font-mono font-semibold">{totalCost.toFixed(4)}</td>
            </tr>
          </tfoot>
        </table>
      </Table>

      <p className="text-xs text-ink-soft">
        Оценка по объявленным ценам OpenAI, не биллинговые данные.
      </p>
    </div>
  );
}
```

- [ ] **Step 2: Run the test file to verify all 6 cases still pass unchanged**

Run: `npx vitest run components/UsageTable.test.tsx`
Expected: PASS (6 tests, no new cases — see the note above).

- [ ] **Step 3: Rewrite `app/usage/page.tsx`**

Replace the full content of `services/admin-web/app/usage/page.tsx`:

```tsx
import { redirect } from "next/navigation";
import { UsageTable } from "@/components/UsageTable";
import { PageHeader } from "@/components/ui/PageHeader";
import { fetchUsage, type UsagePeriod } from "@/lib/api";
import { currentUserIsOwner } from "@/lib/currentUser";
import { API_INTERNAL_URL, API_PROXY_PATH } from "@/lib/env";

const DEFAULT_PERIOD: UsagePeriod = "30d";

export default async function UsagePage() {
  if (!(await currentUserIsOwner())) {
    redirect("/bots");
  }

  const summaries = await fetchUsage(API_INTERNAL_URL, DEFAULT_PERIOD);

  return (
    <main>
      <PageHeader title="Расходы OpenAI" />
      <UsageTable apiBaseUrl={API_PROXY_PATH} summaries={summaries} initialPeriod={DEFAULT_PERIOD} />
    </main>
  );
}
```

- [ ] **Step 4: Run the full suite, typecheck and the build**

Run: `npm test`
Expected: full existing suite passes.

Run: `npx tsc --noEmit`
Expected: clean.

Run: `npm run build`
Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add services/admin-web/components/UsageTable.tsx services/admin-web/app/usage/page.tsx
git commit -m "feat(admin-web): migrate UsageTable and its page to the design system"
```

---

## After this plan

Per the spec's rollout order, the next and final screen-group is `/login`
— a special case: no sidebar (outside the authenticated shell), a
centered card on `--canvas`. After that, the last remaining item across
the whole redesign is deleting the legacy `@layer base` CSS block in
`app/globals.css` once no screen depends on it anymore (verify with a
repo-wide grep for the bare tags it targets before removing). Do not
start either without confirming with the human partner first.
