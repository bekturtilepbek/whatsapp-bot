# Cabinet Redesign — Prompts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate `/bots/[id]/prompts` (`PromptEditor`, rendered three times
on the page — main/image/pdf) onto the `components/ui/` design system —
the sixth screen-group wave, no new primitives, no business-logic changes.

**Architecture:** Same discipline as every previous wave: JSX-only restyle,
save/rollback logic untouched, existing tests are the regression contract,
every `<label>` gets an explicit `mb-0` from the start. `PromptEditor` is a
single component used three times per page (one per prompt kind), so this
plan is one task covering the component and its page together — matching
the actual size of the work. Unlike `DocumentsTable`/`BlockedNumbersTable`,
the "empty" case here (no version history yet) is not the screen's primary
content — it is a secondary sub-section below an always-present editor — so
it gets no `EmptyState`; the history `Table` simply does not render when
there are no versions (same reasoning as `hasMore` gating "Показать ещё" in
`BlockedNumbersTable`, just for a whole section rather than one button).
The page drops its own `<h1>`/back-link (redundant — `app/bots/[id]/layout.tsx`
already shows the bot's name and the matching "Промпты" tab) but keeps its
own `<main>`.

**Tech Stack:** Next.js 15 (App Router, React 19 Server Components),
Tailwind CSS v4 + `components/ui/` primitives (already in `dev`), vitest +
@testing-library/react.

**Spec:** `docs/superpowers/specs/2026-09-13-cabinet-redesign-design.md`
(screen-group 7: "Промпты")

## Global Constraints

- **Tokens are the only source of color/font values** — every className
  reads a Tailwind utility already defined by the `@theme` block.
- **Every `<label>` gets an explicit `mb-0`**, spacing rhythm comes from
  `space-y-*`/`gap-*` on a wrapping element.
- **No redundant `aria-label`.** When a `<label>` already wraps a field
  with visible text, the field gets no `aria-label` duplicating that same
  text (the lesson from the documents/blocked-numbers wave's final
  review — `docs/superpowers/plans/2026-09-15-cabinet-docs-blocklist.md`).
- **Existing tests are the regression contract.** `components/PromptEditor.test.tsx`
  gets exactly ONE new test case appended (the no-history-table case) —
  every other case stays verbatim.
- **Every route supplies its own single `<main>`.**
- Section heading (`<h2>`) carries the specific prompt name ("Основной
  промпт" / "Промпт для фото" / "Промпт для PDF") — matches the
  `BotSettingsForm`/`RenameBotForm` convention of an `<h2>` per `Card`
  naming that section, with the field's own `<label>` text staying
  generic ("Текст промпта").
- Conventional Commits; the task commits its own working, tested slice.

---

### Task 1: `PromptEditor` + `/bots/[id]/prompts` page

**Files:**
- Modify: `services/admin-web/components/PromptEditor.tsx`
- Modify: `services/admin-web/components/PromptEditor.test.tsx` (append
  one test only)
- Modify: `services/admin-web/app/bots/[id]/prompts/page.tsx`

**Interfaces:**
- Consumes: `Card`, `Textarea`, `Button`, `Table` (existing primitives).

- [ ] **Step 1: Add the one new test case to `PromptEditor.test.tsx` (every existing case stays untouched)**

Append to the end of `services/admin-web/components/PromptEditor.test.tsx`:

```tsx
it("renders version history as a table", () => {
  render(
    <PromptEditor
      botId="1"
      apiBaseUrl="http://api"
      kind="main"
      label="Основной промпт"
      initialBody="текущий текст"
      initialVersions={[existingVersion]}
    />,
  );
  expect(screen.getByRole("table")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the test file to verify the new case fails**

Run: `npx vitest run components/PromptEditor.test.tsx`
Expected: the 4 pre-existing tests PASS, the new one FAILS — the current
component renders version history as a bare `<ul>`, not a `<table>`, so
`getByRole("table")` finds nothing yet.

- [ ] **Step 3: Rewrite `PromptEditor.tsx`**

Replace the full content of `services/admin-web/components/PromptEditor.tsx`:

```tsx
"use client";

import { useState } from "react";
import { fetchPromptVersions, patchBotPrompt, type PromptKind, type PromptVersion } from "@/lib/api";
import { useToast } from "@/components/ToastProvider";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Table } from "@/components/ui/Table";
import { Textarea } from "@/components/ui/Textarea";

interface PromptEditorProps {
  botId: string;
  apiBaseUrl: string;
  kind: PromptKind;
  label: string;
  initialBody: string | null;
  initialVersions: PromptVersion[];
}

export function PromptEditor({
  botId,
  apiBaseUrl,
  kind,
  label,
  initialBody,
  initialVersions,
}: PromptEditorProps) {
  const { showError, showSuccess } = useToast();
  const [body, setBody] = useState(initialBody ?? "");
  const [versions, setVersions] = useState<PromptVersion[]>(initialVersions);
  const [saving, setSaving] = useState(false);

  const save = async (newBody: string) => {
    setSaving(true);
    try {
      await patchBotPrompt(apiBaseUrl, botId, kind, newBody);
      setBody(newBody);
      const updated = await fetchPromptVersions(apiBaseUrl, botId, kind);
      setVersions(updated);
      showSuccess("Сохранено");
    } catch (err) {
      showError(err instanceof Error ? err.message : "Не удалось сохранить");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-5">
      <Card className="p-5">
        <h2 className="mb-4 text-[15px] font-semibold text-ink">{label}</h2>
        <label className="mb-0 block text-sm font-medium text-ink">
          Текст промпта
          <Textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={6}
            className="mt-1.5"
          />
        </label>
        <div className="mt-3">
          <Button onClick={() => void save(body)} disabled={saving}>
            {saving ? "Сохраняем…" : "Сохранить"}
          </Button>
        </div>
      </Card>

      {versions.length > 0 && (
        <Table>
          <table>
            <thead>
              <tr>
                <th>Дата</th>
                <th>Автор</th>
                <th>Текст</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {versions.map((version) => (
                <tr key={version.id}>
                  {/* Чистая строковая операция над ISO-текстом, не new Date(...) —
                   * иначе разное форматирование на SSR и на клиенте даёт
                   * hydration-mismatch (урок QR-экрана, components/QrPanel.tsx). */}
                  <td className="font-mono">
                    {version.created_at.slice(0, 16).replace("T", " ")}
                  </td>
                  <td>{version.author}</td>
                  <td>{(version.body ?? "").slice(0, 60)}</td>
                  <td>
                    <Button
                      variant="secondary"
                      onClick={() => void save(version.body ?? "")}
                      disabled={saving}
                    >
                      Откатить
                    </Button>
                  </td>
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

- [ ] **Step 4: Run the test file to verify all 5 cases pass**

Run: `npx vitest run components/PromptEditor.test.tsx`
Expected: PASS (5 tests — the original 4 plus the new no-history-table
case).

- [ ] **Step 5: Rewrite `app/bots/[id]/prompts/page.tsx`**

Replace the full content of `services/admin-web/app/bots/[id]/prompts/page.tsx`:

```tsx
import { notFound } from "next/navigation";
import { PromptEditor } from "@/components/PromptEditor";
import { fetchBot, fetchPromptVersions } from "@/lib/api";
import { API_INTERNAL_URL, API_PROXY_PATH } from "@/lib/env";

export default async function BotPromptsPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const bot = await fetchBot(API_INTERNAL_URL, id);
  if (!bot) {
    notFound();
  }

  const [mainVersions, imageVersions, pdfVersions] = await Promise.all([
    fetchPromptVersions(API_INTERNAL_URL, id, "main"),
    fetchPromptVersions(API_INTERNAL_URL, id, "image"),
    fetchPromptVersions(API_INTERNAL_URL, id, "pdf"),
  ]);

  return (
    <main className="space-y-5">
      <PromptEditor
        botId={id}
        apiBaseUrl={API_PROXY_PATH}
        kind="main"
        label="Основной промпт"
        initialBody={bot.system_prompt}
        initialVersions={mainVersions}
      />
      <PromptEditor
        botId={id}
        apiBaseUrl={API_PROXY_PATH}
        kind="image"
        label="Промпт для фото"
        initialBody={bot.image_prompt}
        initialVersions={imageVersions}
      />
      <PromptEditor
        botId={id}
        apiBaseUrl={API_PROXY_PATH}
        kind="pdf"
        label="Промпт для PDF"
        initialBody={bot.pdf_prompt}
        initialVersions={pdfVersions}
      />
    </main>
  );
}
```

- [ ] **Step 6: Run the full suite, typecheck and the build**

Run: `npm test`
Expected: full existing suite passes, including the now-5-test
`PromptEditor.test.tsx`.

Run: `npx tsc --noEmit`
Expected: clean.

Run: `npm run build`
Expected: build succeeds.

- [ ] **Step 7: Commit**

```bash
git add services/admin-web/components/PromptEditor.tsx services/admin-web/components/PromptEditor.test.tsx \
  services/admin-web/app/bots/\[id\]/prompts/page.tsx
git commit -m "feat(admin-web): migrate PromptEditor and its page to the design system"
```

---

## After this plan

Per the spec's rollout order, the next screen-group candidates are: the
sandbox chrome, then the owner-only platform screens (dashboard, users,
audit-log, usage), then `/login`. Do not start these without confirming
with the human partner first.
