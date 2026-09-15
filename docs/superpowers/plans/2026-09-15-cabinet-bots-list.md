# Cabinet Redesign — Bots List Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate `/bots` (bot list) and `/bots/new` (bot creation) onto the
`components/ui/` design system shipped by the cabinet-redesign-foundation
plan — the second of the spec's screen-group waves, no new primitives, no
business-logic changes.

**Architecture:** `BotsTable` and `NewBotForm` are rebuilt on the existing
primitives (`Table`, `StatusPulse`, `Badge`, `EmptyState`, `PageHeader`,
`Button`, `Input`, `Card`) with their externally-observable behavior
(accessible names, roles, hrefs) unchanged, so their existing test suites
stay the regression contract. One real fix rides along: the bot-detail
layout's `toConnectionStatus` mapping (added in the foundation plan's final
review) is extracted to a shared `lib/botStatus.ts` so the bots list uses
the same `Bot.status`-aware logic instead of re-deriving status from
`linked_at` alone — avoiding a second copy of the exact bug that was just
fixed on the bot-detail page.

**Tech Stack:** Next.js 15 (App Router, React 19 Server Components),
Tailwind CSS v4 + `components/ui/` primitives (already in `dev`), vitest +
@testing-library/react.

**Spec:** `docs/superpowers/specs/2026-09-13-cabinet-redesign-design.md`
(screen-group 3: "Список и создание ботов")

## Global Constraints

- **Tokens are the only source of color/font values** — every className
  reads a Tailwind utility derived from the `@theme` block in
  `app/globals.css` (`bg-accent`, `text-ink-soft`, `font-mono`, …), never a
  raw hex value.
- **`Bot.status` is the source of truth for connection status**, `linked_at`
  is only the fallback for fixtures that don't set `status` — this is the
  exact rule already implemented in `app/bots/[id]/layout.tsx`
  (`toConnectionStatus`), extracted to `lib/botStatus.ts` by Task 1 of this
  plan and reused everywhere a `StatusPulse` needs a status.
- **Existing tests are the regression contract.** `components/BotsTable.test.tsx`
  and `components/NewBotForm.test.tsx` must keep passing; new test cases are
  *added* to them, existing ones are not rewritten unless a task explicitly
  says a specific assertion changes.
- **Component tests that need toast context import from `@/lib/test-utils`**,
  not `@testing-library/react` directly (see the header comment in that
  file) — `NewBotForm.test.tsx` already does this; keep it that way.
- Conventional Commits; every task commits its own working, tested slice.

---

### Task 1: Shared `toConnectionStatus` helper

**Files:**
- Create: `services/admin-web/lib/botStatus.ts`
- Test: `services/admin-web/lib/botStatus.test.ts`
- Modify: `services/admin-web/app/bots/[id]/layout.tsx`

**Interfaces:**
- Produces: `toConnectionStatus(bot: Bot): BotConnectionStatus` — moved
  verbatim from `app/bots/[id]/layout.tsx`'s private function of the same
  name. Task 2's `BotsTable` imports this from `lib/botStatus.ts`.
- Consumes: `Bot` (`lib/api.ts`), `BotConnectionStatus`
  (`components/ui/StatusPulse.tsx`) — both already exist, unchanged.

- [ ] **Step 1: Write the failing test**

Create `services/admin-web/lib/botStatus.test.ts`:

```ts
import { expect, it } from "vitest";
import { toConnectionStatus } from "@/lib/botStatus";
import type { Bot } from "@/lib/api";

const baseBot: Bot = {
  id: "1",
  name: "Тест",
  enabled: true,
  phone: null,
  linked_at: null,
  system_prompt: "",
  image_prompt: null,
  pdf_prompt: null,
};

it("maps status=open to connected", () => {
  expect(toConnectionStatus({ ...baseBot, status: "open" })).toBe("connected");
});

it("maps connecting/qr/reconnecting to pending", () => {
  expect(toConnectionStatus({ ...baseBot, status: "connecting" })).toBe("pending");
  expect(toConnectionStatus({ ...baseBot, status: "qr" })).toBe("pending");
  expect(toConnectionStatus({ ...baseBot, status: "reconnecting" })).toBe("pending");
});

it("maps logged_out to disconnected even when linked_at is still set", () => {
  expect(
    toConnectionStatus({ ...baseBot, status: "logged_out", linked_at: "2026-01-01T00:00:00Z" }),
  ).toBe("disconnected");
});

it("falls back to linked_at when status is absent (older fixtures)", () => {
  expect(toConnectionStatus({ ...baseBot, linked_at: "2026-01-01T00:00:00Z" })).toBe("connected");
  expect(toConnectionStatus({ ...baseBot })).toBe("disconnected");
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npx vitest run lib/botStatus.test.ts`
Expected: FAIL — `Cannot find module '@/lib/botStatus'`.

- [ ] **Step 3: Create the helper**

Create `services/admin-web/lib/botStatus.ts`:

```ts
// Единая логика статуса подключения бота (FEATURES.md 6.17) —
// переиспользуется везде, где показывается StatusPulse: карточка бота
// (app/bots/[id]/layout.tsx) и список ботов (components/BotsTable.tsx).
// Раньше жила только в layout.tsx — вынесена сюда, чтобы список ботов не
// завёл свою версию с тем же багом, что уже был найден и исправлен на
// карточке бота (финальное ревью cabinet-redesign-foundation, 2026-09-15):
// bot.status — источник истины, linked_at — только фолбэк для старых
// фикстур без этого поля.
import type { Bot } from "@/lib/api";
import type { BotConnectionStatus } from "@/components/ui/StatusPulse";

export function toConnectionStatus(bot: Bot): BotConnectionStatus {
  switch (bot.status) {
    case "open":
      return "connected";
    case "connecting":
    case "qr":
    case "reconnecting":
      return "pending";
    case "logged_out":
      return "disconnected";
    default:
      return bot.linked_at ? "connected" : "disconnected";
  }
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `npx vitest run lib/botStatus.test.ts`
Expected: PASS (4 tests).

- [ ] **Step 5: Refactor `app/bots/[id]/layout.tsx` to use the shared helper**

Replace the import block and delete the local `toConnectionStatus` function.
Current lines 1-25:

```tsx
import type { ReactNode } from "react";
import { notFound } from "next/navigation";
import { StatusPulse, type BotConnectionStatus } from "@/components/ui/StatusPulse";
import { Tabs } from "@/components/ui/Tabs";
import { TabLink } from "@/components/ui/TabLink";
import { fetchBot, type Bot } from "@/lib/api";
import { currentUserIsOwner } from "@/lib/currentUser";
import { API_INTERNAL_URL } from "@/lib/env";

function toConnectionStatus(bot: Bot): BotConnectionStatus {
  switch (bot.status) {
    case "open":
      return "connected";
    case "connecting":
    case "qr":
    case "reconnecting":
      return "pending";
    case "logged_out":
      return "disconnected";
    default:
      // status отсутствует (старые фикстуры без этого поля, см. комментарий
      // у Bot.status в lib/api.ts) — падаем обратно на linked_at.
      return bot.linked_at ? "connected" : "disconnected";
  }
}
```

Replace with:

```tsx
import type { ReactNode } from "react";
import { notFound } from "next/navigation";
import { StatusPulse } from "@/components/ui/StatusPulse";
import { Tabs } from "@/components/ui/Tabs";
import { TabLink } from "@/components/ui/TabLink";
import { fetchBot } from "@/lib/api";
import { toConnectionStatus } from "@/lib/botStatus";
import { currentUserIsOwner } from "@/lib/currentUser";
import { API_INTERNAL_URL } from "@/lib/env";
```

The rest of the file (the `BotLayout` function body, which calls
`toConnectionStatus(bot)`) is unchanged — only the import block shrinks and
the function definition is deleted.

- [ ] **Step 6: Run the layout test and the new helper test together**

Run: `npx vitest run app/bots/\[id\]/layout.test.tsx lib/botStatus.test.ts`
Expected: PASS (both files' tests — `layout.test.tsx`'s 4 tests are
unaffected since the refactor doesn't change `BotLayout`'s behavior).

- [ ] **Step 7: Commit**

```bash
git add services/admin-web/lib/botStatus.ts services/admin-web/lib/botStatus.test.ts \
  services/admin-web/app/bots/\[id\]/layout.tsx
git commit -m "refactor(admin-web): extract shared toConnectionStatus helper"
```

---

### Task 2: `BotsTable` + `/bots` page on the design system

**Files:**
- Modify: `services/admin-web/components/BotsTable.tsx`
- Modify: `services/admin-web/components/BotsTable.test.tsx` (add cases only)
- Modify: `services/admin-web/app/bots/page.tsx`
- Modify: `services/admin-web/components/ui/Button.tsx` (export the class
  strings so a `<Link>` can be styled identically to a `<Button>` — see
  Interfaces)

**Interfaces:**
- Produces (new from `Button.tsx`): `BUTTON_BASE_CLASSES: string`,
  `BUTTON_VARIANT_CLASSES: Record<ButtonVariant, string>`,
  `export type ButtonVariant`. `Button` itself is refactored to compose
  from these two constants — its own rendered className is byte-identical
  to before, so `Button.test.tsx` needs no changes. This lets
  `app/bots/page.tsx`'s "Создать бота →" — a *navigation*, not a form
  submit, so it must be an `<a>` via `next/link`, and a `<button>` cannot
  legally nest inside an `<a>` — reuse the exact same visual classes
  without duplicating the literal Tailwind string.
- Consumes: `toConnectionStatus` (Task 1), `Table`/`StatusPulse`/`Badge`/`EmptyState`/`PageHeader` (existing primitives, unchanged).

- [ ] **Step 1: Add new test cases to `BotsTable.test.tsx` (existing three stay untouched)**

Add these to the end of `services/admin-web/components/BotsTable.test.tsx`
(keep every existing `it(...)` in the file exactly as-is; only append):

```tsx
it("shows a paused badge for a disabled bot", () => {
  const paused: Bot[] = [{ ...bots[0], enabled: false }];
  render(<BotsTable bots={paused} />);
  expect(screen.getByText("на паузе")).toBeInTheDocument();
});

it("shows the pending status for a bot mid-connection", () => {
  const pending: Bot[] = [{ ...bots[0], status: "qr", linked_at: null }];
  render(<BotsTable bots={pending} />);
  expect(screen.getByText("Ждёт QR")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the test file to verify the two new cases fail**

Run: `npx vitest run components/BotsTable.test.tsx`
Expected: the 3 pre-existing tests PASS, the 2 new ones FAIL (`на паузе`
and `Ждёт QR` not found — current markup has neither).

- [ ] **Step 3: Export shared button classes from `Button.tsx`**

Replace the full content of `services/admin-web/components/ui/Button.tsx`:

```tsx
import type { ButtonHTMLAttributes } from "react";

export type ButtonVariant = "primary" | "secondary" | "danger";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
}

export const BUTTON_BASE_CLASSES =
  "inline-flex items-center gap-2 rounded-md px-3.5 py-2 text-sm font-medium leading-tight transition-colors disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2";

export const BUTTON_VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary: "bg-accent text-white hover:bg-accent-hover",
  secondary: "bg-surface text-ink border border-border hover:border-ink-faint",
  danger: "bg-surface text-danger border border-danger hover:bg-danger/5",
};

export function Button({ variant = "primary", className = "", ...props }: ButtonProps) {
  return (
    <button
      className={`${BUTTON_BASE_CLASSES} ${BUTTON_VARIANT_CLASSES[variant]} ${className}`}
      {...props}
    />
  );
}
```

- [ ] **Step 4: Run `Button.test.tsx` to confirm the refactor changed nothing observable**

Run: `npx vitest run components/ui/Button.test.tsx`
Expected: PASS (5 tests, unchanged — the rendered className string is
identical to before, just assembled from named constants).

- [ ] **Step 5: Rewrite `BotsTable.tsx`**

Replace the full content of `services/admin-web/components/BotsTable.tsx`:

```tsx
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
```

- [ ] **Step 6: Run `BotsTable.test.tsx` to verify all 5 tests pass**

Run: `npx vitest run components/BotsTable.test.tsx`
Expected: PASS (5 tests — the original 3 plus the 2 added in Step 1).

- [ ] **Step 7: Rewrite `app/bots/page.tsx`**

Replace the full content of `services/admin-web/app/bots/page.tsx`:

```tsx
import Link from "next/link";
import { BotsTable } from "@/components/BotsTable";
import { BUTTON_BASE_CLASSES, BUTTON_VARIANT_CLASSES } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { fetchBots } from "@/lib/api";
import { currentUserIsOwner } from "@/lib/currentUser";
import { API_INTERNAL_URL } from "@/lib/env";

export default async function BotsPage() {
  const [bots, isOwner] = await Promise.all([fetchBots(API_INTERNAL_URL), currentUserIsOwner()]);

  return (
    <main>
      <PageHeader
        title="Боты"
        subtitle={`Ботов: ${bots.length}`}
        action={
          isOwner ? (
            <Link
              href="/bots/new"
              className={`${BUTTON_BASE_CLASSES} ${BUTTON_VARIANT_CLASSES.primary}`}
            >
              Создать бота →
            </Link>
          ) : undefined
        }
      />
      <BotsTable bots={bots} />
    </main>
  );
}
```

- [ ] **Step 8: Run the full suite and the build**

Run: `npm test`
Expected: full existing suite passes, including the now-6-test
`BotsTable.test.tsx` and `Button.test.tsx`.

Run: `npm run build`
Expected: build succeeds.

- [ ] **Step 9: Commit**

```bash
git add services/admin-web/components/BotsTable.tsx services/admin-web/components/BotsTable.test.tsx \
  services/admin-web/components/ui/Button.tsx services/admin-web/app/bots/page.tsx
git commit -m "feat(admin-web): migrate BotsTable and /bots to the design system"
```

---

### Task 3: `NewBotForm` + `/bots/new` page on the design system

**Files:**
- Modify: `services/admin-web/components/NewBotForm.tsx`
- Modify: `services/admin-web/app/bots/new/page.tsx`

**Interfaces:**
- Consumes: `Button`, `Input`, `Card`, `PageHeader` (existing primitives).
- `NewBotForm`'s external behavior (props, `aria-label="Имя"` on the field,
  the exact button text `"Создать"` / `"Создаём…"`, the `useToast()` calls,
  the `router.push`/`router.refresh` calls) is unchanged — `NewBotForm.test.tsx`
  must pass with **zero edits**.

- [ ] **Step 1: Confirm the existing test currently passes (baseline)**

Run: `npx vitest run components/NewBotForm.test.tsx`
Expected: PASS (3 tests) — baseline before touching the component.

- [ ] **Step 2: Rewrite `NewBotForm.tsx`**

Replace the full content of `services/admin-web/components/NewBotForm.tsx`:

```tsx
"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { createBot } from "@/lib/api";
import { useToast } from "@/components/ToastProvider";

interface NewBotFormProps {
  apiBaseUrl: string;
}

export function NewBotForm({ apiBaseUrl }: NewBotFormProps) {
  const router = useRouter();
  const { showError, showSuccess } = useToast();
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim()) {
      return;
    }
    setCreating(true);
    try {
      const bot = await createBot(apiBaseUrl, name);
      showSuccess("Бот создан");
      router.push(`/bots/${bot.id}`);
      router.refresh();
    } catch (err) {
      showError(err instanceof Error ? err.message : "Не удалось создать бота");
      setCreating(false);
    }
  };

  return (
    <form onSubmit={(event) => void handleSubmit(event)}>
      <label className="mb-4 block text-sm font-medium text-ink">
        Имя
        <Input
          type="text"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Название бота"
          aria-label="Имя"
          autoFocus
          className="mt-1.5"
        />
      </label>
      <Button type="submit" disabled={creating}>
        {creating ? "Создаём…" : "Создать"}
      </Button>
    </form>
  );
}
```

- [ ] **Step 3: Run the test again to confirm it still passes, unmodified**

Run: `npx vitest run components/NewBotForm.test.tsx`
Expected: PASS (3 tests) — same assertions, against the restyled markup.

- [ ] **Step 4: Rewrite `app/bots/new/page.tsx`**

Replace the full content of `services/admin-web/app/bots/new/page.tsx`:

```tsx
import Link from "next/link";
import { redirect } from "next/navigation";
import { NewBotForm } from "@/components/NewBotForm";
import { Card } from "@/components/ui/Card";
import { PageHeader } from "@/components/ui/PageHeader";
import { currentUserIsOwner } from "@/lib/currentUser";
import { API_PROXY_PATH } from "@/lib/env";

export default async function NewBotPage() {
  if (!(await currentUserIsOwner())) {
    redirect("/bots");
  }

  return (
    <main>
      <Link href="/bots" className="text-sm text-ink-soft hover:text-ink">
        ← Назад к списку
      </Link>
      <PageHeader title="Новый бот" />
      <Card className="max-w-sm p-5">
        <NewBotForm apiBaseUrl={API_PROXY_PATH} />
      </Card>
    </main>
  );
}
```

- [ ] **Step 5: Run the full suite, typecheck, and build**

Run: `npm test`
Expected: full existing suite passes (189 + the 4 new from Task 1 + the 2
new from Task 2 = 195 total).

Run: `npx tsc --noEmit`
Expected: clean.

Run: `npm run build`
Expected: build succeeds.

- [ ] **Step 6: Commit**

```bash
git add services/admin-web/components/NewBotForm.tsx services/admin-web/app/bots/new/page.tsx
git commit -m "feat(admin-web): migrate NewBotForm and /bots/new to the design system"
```

---

## After this plan

Next screen-group plan per the spec's inventory: bot-scoped dialogue
settings (`/bots/[id]/settings` — `BotSettingsForm` + `RenameBotForm`).
