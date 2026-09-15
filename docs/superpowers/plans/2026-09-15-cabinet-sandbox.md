# Cabinet Redesign — Sandbox Chrome Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the chrome around `/bots/[id]/sandbox` onto the
`components/ui/` design system — the seventh screen-group wave. Unlike
every other wave, `SandboxChat.tsx` itself is explicitly OUT OF SCOPE and
must not be touched.

**Architecture:** The spec is explicit and binding here: "Sandbox-чат
остаётся «телефоном»." `SandboxChat.tsx` is a deliberately WhatsApp-styled
widget built by direct user request (FEATURES.md 9.6) — its internal
styling (the `sbx-*` classes, the inline `<style>` block, the phone/bubble
visual language) is a separate, intentional design system from the rest of
the cabinet and stays untouched. The only change in this wave is the page
chrome: `app/bots/[id]/sandbox/page.tsx` drops its own `<h1>Песочница</h1>`
(redundant — `app/bots/[id]/layout.tsx` already shows the bot's name and
the matching "Песочница" tab, same as every other bot-scoped subpage
migrated in prior waves) but keeps its own `<main>`. No new primitives, no
business-logic changes, no test changes (nothing in `SandboxChat.test.tsx`
depends on the removed `<h1>`, and the page itself has no dedicated test
file — confirmed absent, same as every other bot subpage).

**Tech Stack:** Next.js 15 (App Router, React 19 Server Components),
Tailwind CSS v4 + `components/ui/` primitives (already in `dev`), vitest +
@testing-library/react.

**Spec:** `docs/superpowers/specs/2026-09-13-cabinet-redesign-design.md`
(screen-group 8: "Песочница" — "только чрома вокруг `SandboxChat` (сам
компонент не трогаем)")

## Global Constraints

- **`SandboxChat.tsx` and `SandboxChat.test.tsx` are not touched, at all,
  in this plan.** Not even a lint-motivated formatting change. The spec's
  own words: "его внутренняя стилизация не трогается."
- **Every route supplies its own single `<main>`.**
- Conventional Commits; the task commits its own working, tested slice.

---

### Task 1: `/bots/[id]/sandbox` page chrome

**Files:**
- Modify: `services/admin-web/app/bots/[id]/sandbox/page.tsx`

**Interfaces:**
- Consumes: nothing new — `SandboxChat` (existing, untouched).

- [ ] **Step 1: Rewrite `app/bots/[id]/sandbox/page.tsx`**

Replace the full content of `services/admin-web/app/bots/[id]/sandbox/page.tsx`:

```tsx
import { notFound, redirect } from "next/navigation";
import { SandboxChat } from "@/components/SandboxChat";
import { fetchBot } from "@/lib/api";
import { currentUserIsOwner } from "@/lib/currentUser";
import { API_INTERNAL_URL, API_PROXY_PATH } from "@/lib/env";

export default async function SandboxPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!(await currentUserIsOwner())) {
    redirect(`/bots/${id}`);
  }

  const bot = await fetchBot(API_INTERNAL_URL, id);
  if (!bot) {
    notFound();
  }

  return (
    <main>
      <SandboxChat apiBaseUrl={API_PROXY_PATH} botId={bot.id} botName={bot.name} />
    </main>
  );
}
```

(The only change from the current file: the `<h1>Песочница</h1>` line is
removed. Everything else — the owner-only redirect, `fetchBot`/`notFound`,
props passed to `SandboxChat` — is byte-identical.)

- [ ] **Step 2: Run the full suite, typecheck and the build**

Run: `npm test`
Expected: full existing suite passes unchanged (this page has no dedicated
test file; `SandboxChat.test.tsx`'s cases don't reference the page's own
`<h1>`, so none are affected).

Run: `npx tsc --noEmit`
Expected: clean.

Run: `npm run build`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add services/admin-web/app/bots/\[id\]/sandbox/page.tsx
git commit -m "feat(admin-web): migrate sandbox page chrome to the design system"
```

---

## After this plan

Per the spec's rollout order, the next screen-group is the owner-only
platform section: `/dashboard`, `/users`, `/audit-log`, `/usage`, then
`/login` (a special case — no sidebar, centered card). Do not start these
without confirming with the human partner first.
