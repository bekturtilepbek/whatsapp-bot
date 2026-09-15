# Cabinet Redesign — Documents & Blocked Numbers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate `/bots/[id]/documents` (`DocumentsTable`) and
`/bots/[id]/blocked-numbers` (`BlockedNumbersTable`) onto the
`components/ui/` design system — the fifth screen-group wave, no new
primitives, no business-logic changes.

**Architecture:** Same discipline as every previous wave: JSX-only
restyle, upload/add/delete/pagination logic untouched, existing tests are
the regression contract, every `<label>` gets an explicit `mb-0` from the
start (the lesson from wave 3's final review, already proven correct when
applied proactively in wave 4). Both tables are smaller than `ProductForm`,
so this plan is two tasks, one per screen, each bundling its table
component with its page — matching the actual size of the work rather than
padding to match a fixed task count. Both components gain an `EmptyState`
for the zero-rows case (the same enhancement `BotsTable`/`ProductsTable`
already got); neither needs its own call-to-action inside the empty state,
because each screen's "add" control is an always-visible inline form/file
input sitting above the table, not a separate page-level button that could
duplicate — a different shape from the "Добавить товар" case, but the same
underlying rule: never render two controls for one action. Both pages drop
their own `<h1>`/back-link (redundant — `app/bots/[id]/layout.tsx` already
shows the bot's name and the matching tab) but keep their own `<main>`.

**Tech Stack:** Next.js 15 (App Router, React 19 Server Components),
Tailwind CSS v4 + `components/ui/` primitives (already in `dev`), vitest +
@testing-library/react.

**Spec:** `docs/superpowers/specs/2026-09-13-cabinet-redesign-design.md`
(screen-group 6: "Документы и чёрный список")

## Global Constraints

- **Tokens are the only source of color/font values** — every className
  reads a Tailwind utility already defined by the `@theme` block.
- **Every `<label>` gets an explicit `mb-0`**, spacing rhythm comes from
  `space-y-*`/`gap-*` on a wrapping element.
- **Existing tests are the regression contract.** `components/DocumentsTable.test.tsx`
  and `components/BlockedNumbersTable.test.tsx` each get exactly ONE new
  test case appended (the empty-state case) — every other case stays
  verbatim.
- **Every route supplies its own single `<main>`.**
- **No duplicate call-to-action.** Neither `EmptyState` gets an `action`
  prop — each screen's upload/add control is already permanently visible
  above the table, unlike the products screen where the action lived at
  the page level outside the table component.
- Conventional Commits; every task commits its own working, tested slice.

---

### Task 1: `DocumentsTable` + `/bots/[id]/documents` page

**Files:**
- Modify: `services/admin-web/components/DocumentsTable.tsx`
- Modify: `services/admin-web/components/DocumentsTable.test.tsx` (append
  one test only)
- Modify: `services/admin-web/app/bots/[id]/documents/page.tsx`

**Interfaces:**
- Consumes: `Card`, `Table`, `Button`, `EmptyState` (existing primitives).

- [ ] **Step 1: Add the one new test case to `DocumentsTable.test.tsx` (every existing case stays untouched)**

Append to the end of `services/admin-web/components/DocumentsTable.test.tsx`:

```tsx
it("shows an empty state when there are no documents", () => {
  render(<DocumentsTable botId="1" apiBaseUrl="http://api" documents={[]} />);
  expect(screen.getByText("Документов пока нет")).toBeInTheDocument();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run the test file to verify the new case fails**

Run: `npx vitest run components/DocumentsTable.test.tsx`
Expected: the 6 pre-existing tests PASS, the new one FAILS ("Документов
пока нет" not found — the component currently renders an empty `<table>`
for a zero-length document list, not an empty state).

- [ ] **Step 3: Rewrite `DocumentsTable.tsx`**

Replace the full content of `services/admin-web/components/DocumentsTable.tsx`:

```tsx
"use client";

import { useState } from "react";
import { deleteDocument, uploadDocument, type BotDocument } from "@/lib/api";
import { useToast } from "@/components/ToastProvider";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Table } from "@/components/ui/Table";

interface DocumentsTableProps {
  botId: string;
  apiBaseUrl: string;
  documents: BotDocument[];
}

export function DocumentsTable({ botId, apiBaseUrl, documents }: DocumentsTableProps) {
  const { showError, showSuccess } = useToast();
  const [rows, setRows] = useState(documents);
  const [uploading, setUploading] = useState(false);

  const handleUpload = async (files: FileList | null) => {
    const file = files?.[0];
    if (!file) {
      return;
    }
    setUploading(true);
    try {
      const uploaded = await uploadDocument(apiBaseUrl, botId, file);
      setRows((current) => [uploaded, ...current]);
      showSuccess("Файл загружен");
    } catch (err) {
      showError(err instanceof Error ? err.message : "Не удалось загрузить файл");
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (documentId: string) => {
    try {
      await deleteDocument(apiBaseUrl, botId, documentId);
      setRows((current) => current.filter((row) => row.id !== documentId));
      showSuccess("Файл удалён");
    } catch (err) {
      showError(err instanceof Error ? err.message : "Не удалось удалить");
    }
  };

  return (
    <div className="space-y-5">
      <Card className="p-5">
        <label className="mb-0 block text-sm font-medium text-ink">
          Загрузить файл
          <input
            type="file"
            disabled={uploading}
            onChange={(e) => void handleUpload(e.target.files)}
            aria-label="Файл документа"
            className="mt-1.5 block text-sm text-ink-soft file:mr-3 file:rounded-md file:border file:border-border file:bg-surface file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-ink hover:file:border-ink-faint disabled:opacity-60"
          />
        </label>
        {uploading && <p className="mt-2 text-xs text-ink-soft">Загружаем…</p>}
      </Card>

      {rows.length === 0 ? (
        <EmptyState
          title="Документов пока нет"
          description="Загруженные файлы бот сможет отправлять клиентам по запросу."
        />
      ) : (
        <Table>
          <table>
            <thead>
              <tr>
                <th>Имя файла</th>
                <th>Тип</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((doc) => (
                <tr key={doc.id}>
                  <td>{doc.filename}</td>
                  <td className="font-mono">{doc.mime_type}</td>
                  <td>
                    <Button variant="danger" onClick={() => void handleDelete(doc.id)}>
                      Удалить
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

- [ ] **Step 4: Run the test file to verify all 7 cases pass**

Run: `npx vitest run components/DocumentsTable.test.tsx`
Expected: PASS (7 tests — the original 6 plus the new empty-state case).

- [ ] **Step 5: Rewrite `app/bots/[id]/documents/page.tsx`**

Replace the full content of `services/admin-web/app/bots/[id]/documents/page.tsx`:

```tsx
import { notFound } from "next/navigation";
import { DocumentsTable } from "@/components/DocumentsTable";
import { fetchBot, fetchDocuments } from "@/lib/api";
import { API_INTERNAL_URL, API_PROXY_PATH } from "@/lib/env";

export default async function BotDocumentsPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const bot = await fetchBot(API_INTERNAL_URL, id);
  if (!bot) {
    notFound();
  }
  const documents = await fetchDocuments(API_INTERNAL_URL, id);

  return (
    <main>
      <DocumentsTable botId={id} apiBaseUrl={API_PROXY_PATH} documents={documents} />
    </main>
  );
}
```

- [ ] **Step 6: Run the full suite and the build**

Run: `npm test`
Expected: full existing suite passes, including the now-7-test
`DocumentsTable.test.tsx`.

Run: `npm run build`
Expected: build succeeds.

- [ ] **Step 7: Commit**

```bash
git add services/admin-web/components/DocumentsTable.tsx services/admin-web/components/DocumentsTable.test.tsx \
  services/admin-web/app/bots/\[id\]/documents/page.tsx
git commit -m "feat(admin-web): migrate DocumentsTable and its page to the design system"
```

---

### Task 2: `BlockedNumbersTable` + `/bots/[id]/blocked-numbers` page

**Files:**
- Modify: `services/admin-web/components/BlockedNumbersTable.tsx`
- Modify: `services/admin-web/components/BlockedNumbersTable.test.tsx`
  (append one test only)
- Modify: `services/admin-web/app/bots/[id]/blocked-numbers/page.tsx`

**Interfaces:**
- Consumes: `Card`, `Input`, `Table`, `Button`, `EmptyState` (existing
  primitives).

- [ ] **Step 1: Add the one new test case to `BlockedNumbersTable.test.tsx` (every existing case stays untouched)**

Append to the end of `services/admin-web/components/BlockedNumbersTable.test.tsx`:

```tsx
it("shows an empty state when there are no blocked numbers", () => {
  render(<BlockedNumbersTable botId="1" apiBaseUrl="http://api" numbers={[]} pageSize={10} />);
  expect(screen.getByText("Чёрный список пуст")).toBeInTheDocument();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run the test file to verify the new case fails**

Run: `npx vitest run components/BlockedNumbersTable.test.tsx`
Expected: the 8 pre-existing tests PASS, the new one FAILS.

- [ ] **Step 3: Rewrite `BlockedNumbersTable.tsx`**

Replace the full content of `services/admin-web/components/BlockedNumbersTable.tsx`:

```tsx
"use client";

import { useState, type FormEvent } from "react";
import {
  addBlockedNumber,
  deleteBlockedNumber,
  fetchBlockedNumbers,
  type BlockedNumber,
} from "@/lib/api";
import { useToast } from "@/components/ToastProvider";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Table } from "@/components/ui/Table";

interface BlockedNumbersTableProps {
  botId: string;
  apiBaseUrl: string;
  numbers: BlockedNumber[];
  /** Сколько номеров пришло первой (SSR) страницей — совпадает с limit,
   * которым страница делала fetchBlockedNumbers. Тот же приём, что в
   * ProductsTable: пришло МЕНЬШЕ pageSize — дальше грузить нечего. */
  pageSize: number;
}

export function BlockedNumbersTable({
  botId,
  apiBaseUrl,
  numbers,
  pageSize,
}: BlockedNumbersTableProps) {
  const { showError, showSuccess } = useToast();
  const [rows, setRows] = useState(numbers);
  const [phone, setPhone] = useState("");
  const [adding, setAdding] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(numbers.length === pageSize);

  const handleAdd = async (event: FormEvent) => {
    event.preventDefault();
    if (!phone.trim()) {
      return;
    }
    setAdding(true);
    try {
      const added = await addBlockedNumber(apiBaseUrl, botId, phone);
      // POST идемпотентен: если номер уже был в списке — не дублируем строку.
      setRows((current) =>
        current.some((row) => row.phone === added.phone)
          ? current
          : [added, ...current],
      );
      setPhone("");
      showSuccess("Номер добавлен в чёрный список");
    } catch (err) {
      showError(err instanceof Error ? err.message : "Не удалось добавить");
    } finally {
      setAdding(false);
    }
  };

  const handleDelete = async (targetPhone: string) => {
    try {
      await deleteBlockedNumber(apiBaseUrl, botId, targetPhone);
      setRows((current) => current.filter((row) => row.phone !== targetPhone));
      showSuccess("Номер удалён из чёрного списка");
    } catch (err) {
      showError(err instanceof Error ? err.message : "Не удалось удалить");
    }
  };

  const handleLoadMore = async () => {
    // offset от rows.length — тот же принятый риск сдвига страницы при
    // параллельном изменении списка, что и в ProductsTable.
    setLoadingMore(true);
    try {
      const next = await fetchBlockedNumbers(apiBaseUrl, botId, {
        limit: pageSize,
        offset: rows.length,
      });
      setRows((current) => [...current, ...next]);
      setHasMore(next.length === pageSize);
    } catch (err) {
      showError(err instanceof Error ? err.message : "Не удалось загрузить ещё");
    } finally {
      setLoadingMore(false);
    }
  };

  return (
    <div className="space-y-5">
      <Card className="p-5">
        <form onSubmit={(event) => void handleAdd(event)} className="flex items-end gap-3">
          <label className="mb-0 block flex-1 text-sm font-medium text-ink">
            Номер телефона
            <Input
              type="text"
              value={phone}
              onChange={(event) => setPhone(event.target.value)}
              placeholder="+996 700 00 00 00"
              aria-label="Номер телефона"
              className="mt-1.5"
            />
          </label>
          <Button type="submit" disabled={adding}>
            {adding ? "Добавляем…" : "Добавить"}
          </Button>
        </form>
      </Card>

      {rows.length === 0 ? (
        <EmptyState
          title="Чёрный список пуст"
          description="Заблокированные номера не получают ответов от бота."
        />
      ) : (
        <>
          <Table>
            <table>
              <thead>
                <tr>
                  <th>Номер</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.phone}>
                    <td className="font-mono">{row.phone}</td>
                    <td>
                      <Button variant="danger" onClick={() => void handleDelete(row.phone)}>
                        Удалить
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Table>
          {hasMore && (
            <Button
              variant="secondary"
              onClick={() => void handleLoadMore()}
              disabled={loadingMore}
            >
              {loadingMore ? "Загружаем…" : "Показать ещё"}
            </Button>
          )}
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run the test file to verify all 9 cases pass**

Run: `npx vitest run components/BlockedNumbersTable.test.tsx`
Expected: PASS (9 tests — the original 8 plus the new empty-state case).

- [ ] **Step 5: Rewrite `app/bots/[id]/blocked-numbers/page.tsx`**

Replace the full content of `services/admin-web/app/bots/[id]/blocked-numbers/page.tsx`:

```tsx
import { notFound } from "next/navigation";
import { BlockedNumbersTable } from "@/components/BlockedNumbersTable";
import { fetchBlockedNumbers, fetchBot } from "@/lib/api";
import { API_INTERNAL_URL, API_PROXY_PATH } from "@/lib/env";

// Совпадает с BLOCKED_LIST_DEFAULT_LIMIT в services/api/src/api/routers/
// bots.py — BlockedNumbersTable сравнивает длину полученной страницы с этим
// числом, чтобы понять, есть ли ещё номера ("Показать ещё").
const BLOCKED_PAGE_SIZE = 20;

export default async function BotBlockedNumbersPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const bot = await fetchBot(API_INTERNAL_URL, id);
  if (!bot) {
    notFound();
  }
  const numbers = await fetchBlockedNumbers(API_INTERNAL_URL, id, { limit: BLOCKED_PAGE_SIZE });

  return (
    <main>
      <BlockedNumbersTable
        botId={id}
        apiBaseUrl={API_PROXY_PATH}
        numbers={numbers}
        pageSize={BLOCKED_PAGE_SIZE}
      />
    </main>
  );
}
```

- [ ] **Step 6: Run the full suite, typecheck, and build**

Run: `npm test`
Expected: full existing suite passes, including the now-9-test
`BlockedNumbersTable.test.tsx`.

Run: `npx tsc --noEmit`
Expected: clean.

Run: `npm run build`
Expected: build succeeds.

- [ ] **Step 7: Commit**

```bash
git add services/admin-web/components/BlockedNumbersTable.tsx services/admin-web/components/BlockedNumbersTable.test.tsx \
  services/admin-web/app/bots/\[id\]/blocked-numbers/page.tsx
git commit -m "feat(admin-web): migrate BlockedNumbersTable and its page to the design system"
```

---

## After this plan

Next screen-group plan per the spec's inventory: prompts
(`/bots/[id]/prompts` — `PromptEditor`).
