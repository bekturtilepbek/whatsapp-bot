# Cabinet Redesign — Bot Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate `/bots/[id]/settings` (`RenameBotForm` + `BotSettingsForm`)
onto the `components/ui/` design system — the third screen-group wave, no
new primitives, no business-logic changes.

**Architecture:** Both forms keep every line of validation/diff/save logic
untouched; only the JSX swaps raw `<input>`/`<textarea>`/`<button>` for
`Input`/`NumberField`/`Textarea`/`Switch`/`Button`. `BotSettingsForm`'s four
`<section>` blocks (Батчинг/Хэндофф/Напоминания/Медиа) each become a `Card`
— this is a genuinely multi-section form, so one `Card` per section reads
better than one giant undifferentiated card (unlike `NewBotForm`/
`RenameBotForm`, which are single-field forms and don't need internal
`Card`s of their own — the page wraps them instead). The page itself drops
its own `<h1>`/`← Назад к боту` link, exactly as `app/bots/[id]/page.tsx`
already did in the foundation plan's Task 9 — `app/bots/[id]/layout.tsx`
already renders the bot's name, status, and the "Настройки" tab, so
repeating a heading here is now redundant. **The page keeps its own
`<main>`** (the root layout's wrapper is a plain `<div>`, not a `<main>`,
since the foundation plan's final-review fix — every route supplies
exactly one `<main>` itself).

**Tech Stack:** Next.js 15 (App Router, React 19 Server Components),
Tailwind CSS v4 + `components/ui/` primitives (already in `dev`), vitest +
@testing-library/react.

**Spec:** `docs/superpowers/specs/2026-09-13-cabinet-redesign-design.md`
(screen-group 4: "Диалоговые настройки бота")

## Global Constraints

- **Tokens are the only source of color/font values** — every className
  reads a Tailwind utility already defined by the `@theme` block, never a
  raw hex value.
- **Existing tests are the regression contract.** `components/RenameBotForm.test.tsx`
  and `components/BotSettingsForm.test.tsx` must pass with **zero edits** —
  every `getByLabelText` call relies on the same implicit label-wraps-control
  association the original markup used (no field gains or loses an
  `aria-label` it didn't already have), every checkbox stays a real
  `<input type="checkbox">` (via `Switch`, keeping its native
  `role="checkbox"`), and `noValidate` stays on the `<form>` (HTML5
  min/max validation must not preempt `validateSettings`).
- **Every route supplies its own single `<main>`** — the root layout's
  wrapper div is not one (see Architecture above).
- Conventional Commits; every task commits its own working, tested slice.

---

### Task 1: `RenameBotForm` on the design system

**Files:**
- Modify: `services/admin-web/components/RenameBotForm.tsx`

**Interfaces:**
- Consumes: `Input`, `Button` (existing primitives, unchanged).
- External contract unchanged: `aria-label="Название бота"` on the field,
  button text `"Сохранить"`/`"Сохраняем…"`, `useToast()` calls,
  `router.refresh()` call. `RenameBotForm.test.tsx` must pass with zero edits.

- [ ] **Step 1: Confirm the existing test currently passes (baseline)**

Run: `npx vitest run components/RenameBotForm.test.tsx`
Expected: PASS (4 tests) — baseline before touching the component.

- [ ] **Step 2: Rewrite `RenameBotForm.tsx`**

Replace the full content of `services/admin-web/components/RenameBotForm.tsx`:

```tsx
"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { patchBotName } from "@/lib/api";
import { useToast } from "@/components/ToastProvider";

interface RenameBotFormProps {
  botId: string;
  apiBaseUrl: string;
  initialName: string;
}

export function RenameBotForm({ botId, apiBaseUrl, initialName }: RenameBotFormProps) {
  const router = useRouter();
  const { showError, showSuccess } = useToast();
  const [name, setName] = useState(initialName);
  const [saving, setSaving] = useState(false);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim()) {
      showError("Название не может быть пустым");
      return;
    }
    setSaving(true);
    try {
      await patchBotName(apiBaseUrl, botId, name);
      showSuccess("Название сохранено");
      router.refresh();
    } catch (err) {
      showError(err instanceof Error ? err.message : "Не удалось сохранить название");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={(event) => void handleSubmit(event)}>
      <label className="mb-4 block text-sm font-medium text-ink">
        Название бота
        <Input
          type="text"
          value={name}
          onChange={(event) => setName(event.target.value)}
          aria-label="Название бота"
          className="mt-1.5 max-w-sm"
        />
      </label>
      <Button type="submit" disabled={saving}>
        {saving ? "Сохраняем…" : "Сохранить"}
      </Button>
    </form>
  );
}
```

- [ ] **Step 3: Run the test again to confirm it still passes, unmodified**

Run: `npx vitest run components/RenameBotForm.test.tsx`
Expected: PASS (4 tests) — same assertions, against the restyled markup.

- [ ] **Step 4: Commit**

```bash
git add services/admin-web/components/RenameBotForm.tsx
git commit -m "feat(admin-web): migrate RenameBotForm to the design system"
```

---

### Task 2: `BotSettingsForm` on the design system

**Files:**
- Modify: `services/admin-web/components/BotSettingsForm.tsx`

**Interfaces:**
- Consumes: `Card`, `Input`, `NumberField`, `Textarea`, `Switch`, `Button`
  (existing primitives, unchanged).
- External contract unchanged: every field's accessible name (via implicit
  label-wrapping, same as before — no new `aria-label`s added), the
  `noValidate` attribute, `role="alert"`/`role="status"` via `useToast()`,
  and the exact shape of what `patchBotSettings` is called with (unchanged
  — `diffSettings`/`validateSettings` are not touched by this task at all).
  `BotSettingsForm.test.tsx` must pass with **zero edits**.

- [ ] **Step 1: Confirm the existing test currently passes (baseline)**

Run: `npx vitest run components/BotSettingsForm.test.tsx`
Expected: PASS (11 tests) — baseline before touching the component.

- [ ] **Step 2: Rewrite the component's JSX (keep every other line identical)**

In `services/admin-web/components/BotSettingsForm.tsx`, keep the file's
top (imports below are ADDED to, not replacing, the existing
`patchBotSettings`/`useToast` imports; `BYTES_PER_MB`, `MAX_MEDIA_MAX_SIZE_BYTES`,
`diffSettings`, `validateSettings`, the `BotSettingsFormProps` interface, and
the entire `BotSettingsForm` function body up to and including the
`handleSubmit` definition) **completely unchanged**. Only two things change:
the import block gains the primitive imports, and the `return (...)` JSX is
replaced.

Add these imports alongside the existing ones at the top of the file:

```tsx
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { NumberField } from "@/components/ui/NumberField";
import { Switch } from "@/components/ui/Switch";
import { Textarea } from "@/components/ui/Textarea";
```

Replace the full `return (...)` block (from `return (` through the matching
closing `);` right before the function's closing `}`) with:

```tsx
  return (
    // noValidate — иначе браузерная HTML5-валидация (min/max) тихо блокирует
    // submit ДО того, как выполнится validateSettings ниже: часть невалидных
    // значений (за пределами min/max) вообще не дошла бы до нашего сообщения
    // об ошибке, а показала бы (или не показала бы — зависит от браузера)
    // нативный тултип, при этом другие поля без min/max (текстовые) шли бы
    // через кастомную ошибку — несогласованно.
    <form noValidate onSubmit={(e) => void handleSubmit(e)} className="space-y-5">
      <Card className="p-5">
        <h2 className="mb-4 text-[15px] font-semibold text-ink">Батчинг</h2>
        <label className="block text-sm font-medium text-ink">
          Таймаут батчинга, сек
          <NumberField
            min={0}
            step={0.1}
            value={settings.batch_timeout_seconds}
            onChange={(e) =>
              setSettings({ ...settings, batch_timeout_seconds: Number(e.target.value) })
            }
            className="mt-1.5 max-w-xs"
          />
        </label>
      </Card>

      <Card className="p-5">
        <h2 className="mb-4 text-[15px] font-semibold text-ink">Хэндофф</h2>
        <label className="block text-sm font-medium text-ink">
          Авто-возврат после ответа менеджера, мин
          <NumberField
            min={0}
            step={1}
            value={settings.auto_release_minutes}
            onChange={(e) =>
              setSettings({ ...settings, auto_release_minutes: Number(e.target.value) })
            }
            className="mt-1.5 max-w-xs"
          />
        </label>
      </Card>

      <Card className="p-5">
        <h2 className="mb-4 text-[15px] font-semibold text-ink">Напоминания</h2>
        <label className="mb-4 flex items-center gap-2.5 text-sm font-medium text-ink">
          <Switch
            checked={settings.reminder_enabled}
            onChange={(e) => setSettings({ ...settings, reminder_enabled: e.target.checked })}
          />
          Включены
        </label>
        <label className="mb-4 block text-sm font-medium text-ink">
          Задержка, мин
          <NumberField
            min={0}
            step={1}
            value={settings.reminder_delay_minutes}
            onChange={(e) =>
              setSettings({ ...settings, reminder_delay_minutes: Number(e.target.value) })
            }
            className="mt-1.5 max-w-xs"
          />
        </label>
        <label className="block text-sm font-medium text-ink">
          Текст напоминания
          <Textarea
            rows={3}
            value={settings.reminder_message}
            onChange={(e) => setSettings({ ...settings, reminder_message: e.target.value })}
            className="mt-1.5"
          />
        </label>
      </Card>

      <Card className="p-5">
        <h2 className="mb-4 text-[15px] font-semibold text-ink">Медиа</h2>
        <label className="mb-4 block text-sm font-medium text-ink">
          Заглушка на неподдерживаемое медиа
          <Textarea
            rows={3}
            value={settings.media_fallback_text}
            onChange={(e) => setSettings({ ...settings, media_fallback_text: e.target.value })}
            className="mt-1.5"
          />
        </label>
        <label className="mb-4 block text-sm font-medium text-ink">
          Макс. размер входящего медиа, МБ
          <NumberField
            min={0}
            max={MAX_MEDIA_MAX_SIZE_BYTES / BYTES_PER_MB}
            step={0.1}
            value={settings.media_max_size_bytes / BYTES_PER_MB}
            onChange={(e) =>
              setSettings({
                ...settings,
                media_max_size_bytes: Math.round(Number(e.target.value) * BYTES_PER_MB),
              })
            }
            className="mt-1.5 max-w-xs"
          />
        </label>
        <label className="mb-4 flex items-center gap-2.5 text-sm font-medium text-ink">
          <Switch
            checked={settings.media_reaction_enabled}
            onChange={(e) =>
              setSettings({ ...settings, media_reaction_enabled: e.target.checked })
            }
          />
          Реагировать эмодзи на входящее фото/файл/видео
        </label>
        <label className="block text-sm font-medium text-ink">
          Эмодзи реакции
          <Input
            type="text"
            value={settings.media_reaction_emoji}
            onChange={(e) => setSettings({ ...settings, media_reaction_emoji: e.target.value })}
            className="mt-1.5 max-w-xs"
          />
        </label>
      </Card>

      <Button type="submit" disabled={saving}>
        {saving ? "Сохраняем…" : "Сохранить"}
      </Button>
    </form>
  );
```

- [ ] **Step 3: Run the test to confirm all 11 cases still pass, unmodified**

Run: `npx vitest run components/BotSettingsForm.test.tsx`
Expected: PASS (11 tests) — same assertions, against the restyled markup.
Pay particular attention to the checkbox tests (`getByLabelText(/включены/i)`,
`getByLabelText(/реагировать эмодзи/i)`) and the "converts MB to bytes" /
"sends nothing further once saved" tests — these exercise the exact
`onChange` wiring that must be byte-for-byte preserved.

- [ ] **Step 4: Commit**

```bash
git add services/admin-web/components/BotSettingsForm.tsx
git commit -m "feat(admin-web): migrate BotSettingsForm to the design system"
```

---

### Task 3: `/bots/[id]/settings` page assembly

**Files:**
- Modify: `services/admin-web/app/bots/[id]/settings/page.tsx`

**Interfaces:**
- Consumes: `Card` (existing primitive), `RenameBotForm` (Task 1),
  `BotSettingsForm` (Task 2).
- No test file exists for this page (page-level composition only, no logic
  of its own beyond the existing `fetchBot`/`notFound` guard) — the full
  suite (`RenameBotForm.test.tsx` + `BotSettingsForm.test.tsx`, unaffected
  by this task) is the safety net.

- [ ] **Step 1: Rewrite `app/bots/[id]/settings/page.tsx`**

Replace the full content of `services/admin-web/app/bots/[id]/settings/page.tsx`:

```tsx
import { notFound } from "next/navigation";
import { BotSettingsForm } from "@/components/BotSettingsForm";
import { RenameBotForm } from "@/components/RenameBotForm";
import { Card } from "@/components/ui/Card";
import { DEFAULT_BOT_SETTINGS, fetchBot } from "@/lib/api";
import { API_INTERNAL_URL, API_PROXY_PATH } from "@/lib/env";

export default async function BotSettingsPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const bot = await fetchBot(API_INTERNAL_URL, id);
  if (!bot) {
    notFound();
  }

  const initialSettings = { ...DEFAULT_BOT_SETTINGS, ...bot.settings };

  return (
    <main className="space-y-5">
      <Card className="p-5">
        <RenameBotForm botId={id} apiBaseUrl={API_PROXY_PATH} initialName={bot.name} />
      </Card>
      <BotSettingsForm botId={id} apiBaseUrl={API_PROXY_PATH} initialSettings={initialSettings} />
    </main>
  );
}
```

Note what's deliberately dropped versus the old page: the `← Назад к боту`
link and the `<h1>{bot.name} — настройки</h1>` heading. Both are now
redundant — `app/bots/[id]/layout.tsx` already renders the bot's name,
status, and a "Настройки" tab that's the equivalent of the back-link (one
click away). This mirrors exactly what `app/bots/[id]/page.tsx` (the
"Обзор" tab) already did in the foundation plan.

- [ ] **Step 2: Run the full suite, typecheck, and build**

Run: `npm test`
Expected: full existing suite passes unchanged (195 tests — this task adds
none; `RenameBotForm.test.tsx` and `BotSettingsForm.test.tsx` don't test
`page.tsx` directly).

Run: `npx tsc --noEmit`
Expected: clean.

Run: `npm run build`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add services/admin-web/app/bots/\[id\]/settings/page.tsx
git commit -m "feat(admin-web): assemble /bots/[id]/settings on the design system"
```

---

## After this plan

Next screen-group plan per the spec's inventory: products
(`/bots/[id]/products` — `ProductsTable`, `new`/`edit` — `ProductForm`).
Note for that plan: `app/bots/[id]/products/page.tsx` already has a bare
`<Link href=".../products/new">Добавить товар</Link>` that should use the
`buttonClasses()` helper (`components/ui/Button.tsx`, added by the
bots-list plan) instead of hand-rolling its own button styling.
