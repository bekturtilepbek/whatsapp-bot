# Cabinet Redesign — Legacy CSS Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close out the cabinet redesign (ADR-009): migrate the one
remaining unstyled component (`QrPanel`, deliberately skipped through all
9 prior screen-group waves per the design spec), then delete the
temporary `@layer base` safety-net CSS in `app/globals.css` that every
prior wave preserved for not-yet-migrated screens.

**Architecture:** `QrPanel.tsx` renders `/bots/[id]`'s "Обзор" tab — the
cabinet's most-visited screen — and was excluded from every prior wave on
purpose (the spec's screen-group list never named it; it stayed bare
markup by design, not oversight). Now that everything else is migrated,
it is the last thing standing between "every screen has real classes" and
"the legacy CSS block is provably dead," so this plan does both in one
wave: Task 1 migrates `QrPanel` onto `Card`/`Button`/tokens (no business-
logic change — the poll loop, the deliberately-not-toast inline error, the
disconnect flow are all untouched); Task 2 then deletes the block.

**An independent, repo-wide grep audit was run before writing this plan**
(not just trusting the prior wave's final-review notes) to confirm every
one of the legacy block's selectors is genuinely dead once Task 1 lands:

- `table`/`th`/`td` — every remaining `<table>` in the codebase is inside
  the `Table` primitive, which already styles `th`/`td` via its own
  descendant selectors (`[&_th]`, `[&_td]` in `components/ui/Table.tsx`).
- `textarea` — the one primitive (`components/ui/Textarea.tsx`) sets its
  own width/padding/font explicitly; `SandboxChat.tsx`'s bare `<textarea>`
  (deliberately out of scope, WhatsApp-styled widget) is fully covered by
  its own scoped `.sbx-input-bar textarea` rules.
- `section`/`ul`/`li` — zero remaining JSX consumers anywhere in `app/`
  or `components/` (grepped directly).
- `form label` — every remaining `<label>` in the whole app already sets
  its own `display` (`block` or `flex`) and its own margin utility
  (`mb-0` or the older, still-correct `mb-4` from pre-Global-Constraint
  waves) — none of them structurally depend on the legacy rule; Tailwind's
  utility layer already wins the cascade over `@layer base` regardless.
- `form input[type="number"|"text"|"checkbox"]` — the only remaining bare
  `<input>`s anywhere are `type="file"` (in `DocumentsTable.tsx` and
  `ProductForm.tsx`), which this selector never targeted; every text/
  number/checkbox input goes through `Input`/`NumberField`/`Switch`.
- `body` — `app/layout.tsx`'s `<body>` already carries explicit `m-0
  font-sans text-ink` classes overriding all three legacy properties.

**One finding this audit surfaced that the prior wave's review did not:**
`button { padding: 0.5rem 1rem; cursor: pointer; }` has THREE dependents,
not one. `components/ui/Button.tsx` is the obvious one. But
`components/Sidebar.tsx`'s "Выйти" button and
`components/ToastProvider.tsx`'s "×" close button are ALSO bare
`<button>` elements with their own point classes (`p-0 text-xs ...`) —
neither sets its own `cursor` utility, so both currently get their hand
cursor from this legacy rule too, and deleting it outright would silently
regress the cursor on both (invisible to tests — jsdom doesn't compute
cursor styles). The padding half is safe to delete (every remaining bare
`<button>`, including these two, already sets its own explicit padding).
The cursor half is not worth distributing across three (and growing)
scattered call sites — Task 2 keeps exactly one line,
`button { cursor: pointer; }`, as a deliberate, permanent, documented
base-layer default (not legacy debt), and deletes everything else in the
block.

**Tech Stack:** Next.js 15 (App Router, React 19 Client Component), CSS
(`app/globals.css`, Tailwind v4 `@layer base`), Tailwind CSS v4 +
`components/ui/` primitives (already in `dev`), vitest +
@testing-library/react.

**Spec:** `docs/superpowers/specs/2026-09-13-cabinet-redesign-design.md`.
Not a new screen-group — this is the spec's own closing instruction,
referenced at the end of every prior wave's plan: "правила удаляются
целиком только последним таском самой последней волны редизайна экранов,
когда ни один `<table>`/`<button>` без className их больше не использует"
(`app/globals.css`'s own comment, quoted verbatim).

## Global Constraints

- **Tokens are the only source of color/font values.**
- **No business-logic change anywhere in `QrPanel.tsx`** — the poll
  interval, `refresh()`, `handleLogout()`, the deliberately-inline (not
  toast) `pollError` state and its Russian rationale comment all stay
  byte-identical. Pure JSX/styling migration, exactly like every prior
  wave.
- **`QrPanel.test.tsx` is not touched** — all 6 cases query by
  `getByRole`/`getByText`, none depend on classNames; zero test diff
  expected.
- **Task 2 runs only after Task 1 is committed** — deleting the safety
  net before the last dependent is migrated would be exactly the mistake
  this whole staged-wave approach was designed to avoid.
- **Every route supplies its own single `<main>`** (already true for
  `app/bots/[id]/page.tsx` — untouched by this plan).
- Conventional Commits; each task commits its own working, tested slice.

---

### Task 1: Migrate `QrPanel.tsx`

**Files:**
- Modify: `services/admin-web/components/QrPanel.tsx`

**Interfaces:**
- Consumes: `Button`, `Card` (existing primitives).

- [ ] **Step 1: Rewrite `QrPanel.tsx`**

Replace the full content of `services/admin-web/components/QrPanel.tsx`:

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchBot, logoutBot, qrImageUrl, type Bot } from "@/lib/api";
import { useToast } from "@/components/ToastProvider";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";

interface QrPanelProps {
  initialBot: Bot;
  apiBaseUrl: string;
  /** 5с по умолчанию (FEATURES.md 6.1) — тесты передают меньшее значение
   * вместо фейковых таймеров. */
  pollIntervalMs?: number;
}

export function QrPanel({ initialBot, apiBaseUrl, pollIntervalMs = 5000 }: QrPanelProps) {
  const { showError, showSuccess } = useToast();
  const [bot, setBot] = useState<Bot>(initialBot);
  const [qrUrl, setQrUrl] = useState<string | null>(null);
  const [loggingOut, setLoggingOut] = useState(false);
  // Намеренно НЕ toast: это статус фонового поллинга (каждые pollIntervalMs,
  // 5с в проде), не результат одноразового действия пользователя — toast на
  // каждый неудачный опрос копился бы бесконечной стопкой, пока не
  // восстановится сеть. Постоянный инлайн-баннер здесь уместнее (FEATURES.md
  // 6.5 про алерты РЕЗУЛЬТАТА действия, не про живой статус соединения).
  const [pollError, setPollError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const updated = await fetchBot(apiBaseUrl, initialBot.id);
      setPollError(null);
      if (!updated) return;
      setBot(updated);
      if (!updated.linked_at) {
        // Перегенерируем URL — cache-busting подхватывает ротацию QR (~20с).
        setQrUrl(qrImageUrl(apiBaseUrl, initialBot.id));
      }
    } catch (err) {
      setPollError(err instanceof Error ? err.message : "Не удалось обновить статус");
    }
  }, [apiBaseUrl, initialBot.id]);

  useEffect(() => {
    const timer = setInterval(() => {
      void refresh();
    }, pollIntervalMs);
    return () => clearInterval(timer);
  }, [refresh, pollIntervalMs]);

  // Инициализировать QR-код только на клиенте после монтирования,
  // чтобы избежать гидрацион-mismatch между SSR и клиентом.
  useEffect(() => {
    setQrUrl(qrImageUrl(apiBaseUrl, initialBot.id));
  }, [apiBaseUrl, initialBot.id]);

  const handleLogout = async () => {
    setLoggingOut(true);
    try {
      await logoutBot(apiBaseUrl, bot.id);
      showSuccess("Номер отключён");
    } catch (err) {
      showError(err instanceof Error ? err.message : "Не удалось отключить номер");
    } finally {
      setLoggingOut(false);
    }
    // refresh() безопасен всегда (сам ловит свои ошибки) — вызываем и при
    // успехе, и при неудаче logout, чтобы показать актуальное состояние.
    await refresh();
  };

  if (bot.linked_at) {
    return (
      <Card className="p-5">
        <p className="text-sm text-ink">
          Подключён: <span className="font-mono">{bot.phone}</span>
        </p>
        <div className="mt-3">
          <Button variant="danger" onClick={() => void handleLogout()} disabled={loggingOut}>
            {loggingOut ? "Отключаем…" : "Отключить"}
          </Button>
        </div>
        {pollError && (
          <p role="alert" className="mt-3 text-sm text-danger">
            {pollError}
          </p>
        )}
      </Card>
    );
  }

  return (
    <Card className="p-5">
      <p className="text-sm text-ink">Отсканируйте QR в WhatsApp на телефоне</p>
      {qrUrl && (
        // eslint-disable-next-line @next/next/no-img-element -- PNG отдаёт api напрямую, не статический ассет Next.js
        <img
          src={qrUrl}
          alt="QR-код для подключения WhatsApp"
          width={300}
          height={300}
          className="mt-3 rounded-md border border-border"
        />
      )}
      {pollError && (
        <p role="alert" className="mt-3 text-sm text-danger">
          {pollError}
        </p>
      )}
    </Card>
  );
}
```

(The disconnect button is `variant="danger"` — it severs an active,
working connection, the same severity class as the delete actions
already styled `danger` elsewhere, e.g. `ProductsTable`/`DocumentsTable`.)

- [ ] **Step 2: Run the test file to verify all 6 cases still pass unchanged**

Run: `npx vitest run components/QrPanel.test.tsx`
Expected: PASS (6 tests, zero test-file changes — every query is
`getByRole`/`getByText`/`getByLabelText`, none depend on classNames).

- [ ] **Step 3: Run the full suite, typecheck and the build**

Run: `npm test`
Expected: full existing suite passes.

Run: `npx tsc --noEmit`
Expected: clean.

Run: `npm run build`
Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add services/admin-web/components/QrPanel.tsx
git commit -m "feat(admin-web): migrate QrPanel to the design system"
```

---

### Task 2: Delete the legacy `@layer base` CSS

**Files:**
- Modify: `services/admin-web/app/globals.css`

**Interfaces:** none — pure CSS deletion, no component changes.

- [ ] **Step 1: Replace the `@layer base` block in `globals.css`**

In `services/admin-web/app/globals.css`, replace everything from the
comment block starting `/* Существующие правила ДО этой волны редизайна`
through the closing `}` of `@layer base` (i.e. replace the entire
comment + `@layer base { ... }` block — everything after the `@theme {
... }` block) with:

```css
/* Редизайн кабинета завершён (ADR-009) — все экраны переведены на
 * components/ui/ примитивы, временный @layer base для немигрированных
 * экранов сослужил свою службу и удалён. Единственное намеренно
 * оставленное правило ниже — не легаси, а постоянный маленький дефолт:
 * браузеры по умолчанию НЕ ставят курсор-руку на <button>. Держим его
 * одним общим правилом вместо того, чтобы дублировать cursor-pointer в
 * каждом месте с голым <button> — components/ui/Button.tsx получает
 * курсор отсюда так же, как Sidebar.tsx ("Выйти") и ToastProvider.tsx
 * (кнопка закрытия), у обоих голая точечная разметка без своего примитива. */
@layer base {
  button {
    cursor: pointer;
  }
}
```

The `@theme { ... }` block above it (all 16 color tokens + font
variables) is untouched.

- [ ] **Step 2: Run the full suite, typecheck and the build**

Run: `npm test`
Expected: full existing suite passes (no test in the repo asserts on
computed CSS/cursor styles, so this is a behavior-invisible-to-jsdom
change — the live docker pass is what actually verifies it).

Run: `npx tsc --noEmit`
Expected: clean (CSS-only change, but confirms nothing else broke).

Run: `npm run build`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add services/admin-web/app/globals.css
git commit -m "chore(admin-web): remove the legacy @layer base CSS now that every screen is migrated"
```

---

## After this plan

This closes the cabinet redesign (ADR-009) — every screen listed in the
design spec's rollout order, plus this final cleanup, is done. The live
docker-compose pass after this wave should be a walk across the whole
cabinet (not just one screen), with particular attention to: the cursor
on a `Button`-based button, the cursor on `Sidebar`'s "Выйти" and
`ToastProvider`'s "×" close button (the three dependents this plan found
on the kept rule), and `/bots/[id]`'s "Обзор" tab in both its states
(unlinked — QR code — and linked — phone + disconnect button).
