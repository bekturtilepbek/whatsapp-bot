# Cabinet Redesign — Login Screen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate `/login` onto the `components/ui/` design system — the
ninth and final screen-group wave of the visual redesign. No new
primitives, no business-logic changes, no test changes.

**Architecture:** Per the spec, `/login` is a special case: no sidebar
(it lives outside the authenticated shell), a centered card on
`--canvas`. The "no sidebar" half is already true today with zero code
change needed — `components/Sidebar.tsx:9` (`if (!user) return null`)
already renders nothing for an unauthenticated visitor, and `/login` is
the one route an unauthenticated visitor reaches. This task is therefore
purely `app/login/page.tsx`'s own visual content: replace the bare
`<h1>`/unstyled `<form>` with a centered `Card` containing the same form,
migrated onto `Input`/`Button`.

A small brand mark (the same "Б" badge + "Платформа ботов" name already
in `Sidebar.tsx:13-17`) sits above the card — not mandated by the spec in
so many words, but every login screen in this visual language needs
*something* identifying the product before the form, and reusing the
sidebar's own existing markup fragment (not inventing new content) is the
lowest-risk way to supply it.

**No test changes.** `app/login/page.test.tsx` renders `<LoginPage />`
directly (not the layout) and queries by `getByLabelText("Email"/"Пароль")`
and `getByRole("button"|"alert")` — every one of those already resolves
via the exact same mechanism after this migration (the two fields were
*already* wrapped in `<label>Email<input/></label>`-style implicit
association before this change; only the `<input>` becomes an `<Input>`
and the `<button>` becomes a `<Button>`, both forwarding the same
`name`/`type`/`required`/`disabled`/`autoFocus` props). All 3 existing
tests must pass completely unchanged.

**Tech Stack:** Next.js 15 (App Router, React 19 Client Component —
`page.tsx` is already `"use client"` for `useActionState`), Tailwind CSS
v4 + `components/ui/` primitives (already in `dev`), vitest +
@testing-library/react.

**Spec:** `docs/superpowers/specs/2026-09-13-cabinet-redesign-design.md`
(screen-group 10: "`/login` — отдельно: без сайдбара ..., центрированная
карточка на `--canvas`")

## Global Constraints

- **Tokens are the only source of color/font values.**
- **Every `<label>` gets an explicit `mb-0`** — this one is load-bearing,
  not merely defensive: this form (unlike most other migrated forms) DOES
  sit inside a `<form>`, so `app/globals.css`'s legacy
  `form label { margin-bottom: 1rem }` rule actually applies here.
- **No redundant `aria-label`.** Neither field gets one — the wrapping
  `<label>`'s visible text ("Email"/"Пароль") already supplies the
  accessible name, same as before this migration.
- **`app/login/actions.ts` is not touched** — `login`/`logout` server
  actions, `useActionState` wiring, the `wasPending` ref trick, and its
  Russian-comment rationale all stay byte-identical. Pure JSX/styling
  change.
- **`app/login/page.test.tsx` and `app/login/actions.test.ts` are not
  touched** — zero test diff expected; see Architecture above for why.
- **Every route supplies its own single `<main>`.**
- Conventional Commits.

---

### Task 1: `/login` page

**Files:**
- Modify: `services/admin-web/app/login/page.tsx`

**Interfaces:**
- Consumes: `Button`, `Card`, `Input` (existing primitives).

- [ ] **Step 1: Rewrite `app/login/page.tsx`**

Replace the full content of `services/admin-web/app/login/page.tsx`:

```tsx
"use client";

import { useActionState, useEffect, useRef } from "react";
import { login } from "./actions";
import { useToast } from "@/components/ToastProvider";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";

export default function LoginPage() {
  const { showError } = useToast();
  const [error, formAction, pending] = useActionState(login, null);
  // useActionState не даёт номер попытки — если два неудачных сабмита подряд
  // вернут ОДИНАКОВЫЙ текст ошибки, эффект по [error] не перезапустится
  // (значение не изменилось), и вторая неудача останется без toast. Ловим
  // переход pending true→false вместо значения error — так каждый
  // завершённый сабмит с ошибкой показывает свой toast, даже повторный.
  const wasPending = useRef(false);

  useEffect(() => {
    if (wasPending.current && !pending && error) {
      showError(error);
    }
    wasPending.current = pending;
  }, [pending, error, showError]);

  return (
    <main className="flex h-full items-center justify-center">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center justify-center gap-2">
          <span className="flex h-6 w-6 items-center justify-center rounded-md bg-accent text-xs font-semibold text-white">
            Б
          </span>
          <span className="text-sm font-semibold text-ink">Платформа ботов</span>
        </div>
        <Card className="p-8">
          <h1 className="mb-6 text-lg font-semibold text-ink">Вход</h1>
          <form action={formAction} className="space-y-5">
            <label className="mb-0 block text-sm font-medium text-ink">
              Email
              <Input type="email" name="email" required autoFocus className="mt-1.5" />
            </label>
            <label className="mb-0 block text-sm font-medium text-ink">
              Пароль
              <Input type="password" name="password" required className="mt-1.5" />
            </label>
            <Button type="submit" disabled={pending} className="w-full justify-center">
              {pending ? "Входим…" : "Войти"}
            </Button>
          </form>
        </Card>
      </div>
    </main>
  );
}
```

- [ ] **Step 2: Run the test file to verify all 3 cases still pass unchanged**

Run: `npx vitest run app/login/page.test.tsx`
Expected: PASS (3 tests, no changes needed — see the Architecture note
above for why `getByLabelText`/`getByRole` keep resolving).

- [ ] **Step 3: Run the full suite, typecheck and the build**

Run: `npm test`
Expected: full existing suite passes.

Run: `npx tsc --noEmit`
Expected: clean.

Run: `npm run build`
Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add services/admin-web/app/login/page.tsx
git commit -m "feat(admin-web): migrate the login page to the design system"
```

---

## After this plan

This is the last screen-group in the visual redesign spec's rollout
order. The one remaining item across the WHOLE redesign — not scoped to
this plan — is deleting the legacy `@layer base` CSS block in
`app/globals.css` now that every screen has been migrated. Before
attempting that cleanup: run a repo-wide grep for the bare tags the block
targets (`form label`, `form input[type="checkbox"]`, `button`, `section`,
`ul`, `li`, etc. — check the block's own selectors) across
`app/`/`components/` to confirm nothing still depends on it, since a
false assumption there would silently break whichever screen still relies
on an un-migrated bare tag. Do not start this without confirming with the
human partner first — it's a good moment for a last live docker-compose
pass across the *whole* cabinet, not just one screen, since it closes out
the entire redesign project.
