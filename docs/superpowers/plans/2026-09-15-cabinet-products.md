# Cabinet Redesign — Products Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate `/bots/[id]/products` (`ProductsTable`), `/bots/[id]/products/new`
and `/bots/[id]/products/[productId]/edit` (`ProductForm`) onto the
`components/ui/` design system — the fourth screen-group wave, no new
primitives, no business-logic changes.

**Architecture:** Same discipline as the previous two waves: JSX-only
restyle, validation/diff/save logic untouched, existing tests are the
regression contract. Three deliberate, spec-consistent additions ride
along: (1) `ProductsTable` gets an `EmptyState` for zero products (the
foundation plan's own mockup showed exactly this — "Товаров пока нет"), (2)
the page-level "Добавить товар" action finally uses `buttonClasses()`
(`components/ui/Button.tsx`) instead of a bare unstyled `<Link>` — the
bots-list plan added that helper specifically for this call site, (3)
**every `<label>` in `ProductForm` gets an explicit `mb-0`** from the
start — the previous wave's final review found that `form label {
margin-bottom: 1rem }` (a legacy rule still in `@layer base`) silently
leaks into any label lacking its own margin utility; this plan applies that
lesson proactively instead of waiting for another review round-trip.
`ProductsTable`/`products/page.tsx` and the `new`/`edit` pages both drop
their own redundant `<h1>`/back-link — `app/bots/[id]/layout.tsx` already
renders the bot's name and a "Товары" tab, exactly the pattern already
established on the Обзор and Настройки tabs.

**Tech Stack:** Next.js 15 (App Router, React 19 Server Components),
Tailwind CSS v4 + `components/ui/` primitives (already in `dev`), vitest +
@testing-library/react.

**Spec:** `docs/superpowers/specs/2026-09-13-cabinet-redesign-design.md`
(screen-group 5: "Товары")

## Global Constraints

- **Tokens are the only source of color/font values** — every className
  reads a Tailwind utility already defined by the `@theme` block, never a
  raw hex value or a CSS color keyword like `gray` (the price/SKU/description
  "can't clear back to empty" hints currently use inline `style={{color:
  "gray", ...}}` — this becomes `text-ink-soft`).
- **Every `<label>` gets an explicit `mb-0`**, with actual spacing rhythm
  coming from `space-y-*`/`gap-*` on a wrapping element — never rely on
  the legacy `form label { margin-bottom: 1rem }` rule, intentionally or
  by omission (see Architecture above).
- **Existing tests are the regression contract.** `components/ProductsTable.test.tsx`
  must pass with only ONE new test case appended (the empty-state case) —
  every existing case stays verbatim. `components/ProductForm.test.tsx`
  must pass with **zero edits** — this task adds no new behavior to
  `ProductForm`, only restyles it.
- **Every route supplies its own single `<main>`** — the root layout's
  wrapper is a plain `<div>`, not `<main>`.
- **No duplicate call-to-action.** `ProductsTable`'s empty state does NOT
  get its own "Добавить товар" action — the page above it already has one,
  always visible; repeating it would recreate the exact "two buttons for
  one purpose" problem the previous wave's final review just fixed.
- Conventional Commits; every task commits its own working, tested slice.

---

### Task 1: `ProductsTable` + `/bots/[id]/products` page

**Files:**
- Modify: `services/admin-web/components/ProductsTable.tsx`
- Modify: `services/admin-web/components/ProductsTable.test.tsx` (append
  one test only)
- Modify: `services/admin-web/app/bots/[id]/products/page.tsx`

**Interfaces:**
- Consumes: `Table`, `Button`, `EmptyState` (existing primitives),
  `buttonClasses` (`components/ui/Button.tsx`, added by the bots-list plan
  specifically for this call site — its first real consumer).

- [ ] **Step 1: Add the one new test case to `ProductsTable.test.tsx` (every existing case stays untouched)**

Append to the end of `services/admin-web/components/ProductsTable.test.tsx`:

```tsx
it("shows an empty state when there are no products", () => {
  render(<ProductsTable botId="1" apiBaseUrl="http://api" products={[]} pageSize={10} />);
  expect(screen.getByText("Товаров пока нет")).toBeInTheDocument();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run the test file to verify the new case fails**

Run: `npx vitest run components/ProductsTable.test.tsx`
Expected: the 8 pre-existing tests PASS, the new one FAILS ("Товаров пока
нет" not found — the component currently renders an empty `<table>` for a
zero-length product list, not an empty state).

- [ ] **Step 3: Rewrite `ProductsTable.tsx`**

Replace the full content of `services/admin-web/components/ProductsTable.tsx`:

```tsx
"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { deleteProduct, fetchProducts, productPhotoUrl, type Product } from "@/lib/api";
import { useToast } from "@/components/ToastProvider";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Table } from "@/components/ui/Table";

interface ProductsTableProps {
  botId: string;
  apiBaseUrl: string;
  products: Product[];
  /** Сколько товаров пришло первой (SSR) страницей — совпадает с limit,
   * которым страница делала fetchProducts. Нужно, чтобы понять, есть ли ещё
   * товары: если пришло МЕНЬШЕ pageSize, дальше грузить нечего. */
  pageSize: number;
}

export function ProductsTable({ botId, apiBaseUrl, products, pageSize }: ProductsTableProps) {
  const router = useRouter();
  const { showError, showSuccess } = useToast();
  const [rows, setRows] = useState(products);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(products.length === pageSize);

  const handleDelete = async (productId: string) => {
    if (!confirm("Удалить товар?")) {
      return;
    }
    try {
      await deleteProduct(apiBaseUrl, botId, productId);
      setRows((current) => current.filter((p) => p.id !== productId));
      showSuccess("Товар удалён");
      router.refresh();
    } catch (err) {
      showError(err instanceof Error ? err.message : "Не удалось удалить");
    }
  };

  const handleLoadMore = async () => {
    // offset считается от rows.length — обычный offset-пагинации риск:
    // товар, добавленный/удалённый между страницами (этим админом в другой
    // вкладке или кем-то ещё), может на следующей "Показать ещё" сдвинуть
    // выдачу (пропуск/дубль одной строки). Принято сознательно для витрины
    // кабинета такого масштаба (найдено code review, 2026-09-10) — не чинить
    // курсорной пагинацией без реальной жалобы.
    setLoadingMore(true);
    try {
      const next = await fetchProducts(apiBaseUrl, botId, {
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

  if (rows.length === 0) {
    // Без своей кнопки "Добавить товар" — она уже есть на странице выше
    // (app/bots/[id]/products/page.tsx), повторять здесь = тот же дубль
    // действия, который правили в прошлой волне (RenameBotForm/BotSettingsForm).
    return (
      <EmptyState
        title="Товаров пока нет"
        description="Добавьте первый — он появится в каталоге бота сразу."
      />
    );
  }

  return (
    <>
      <Table>
        <table>
          <thead>
            <tr>
              <th />
              <th>Название</th>
              <th>Цена</th>
              <th>SKU</th>
              <th />
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((product) => (
              <tr key={product.id}>
                <td>
                  {product.photos[0] && (
                    <img
                      src={productPhotoUrl(apiBaseUrl, botId, product.id, product.photos[0].id)}
                      alt={product.name}
                      className="h-12 w-12 rounded-md object-cover"
                    />
                  )}
                </td>
                <td>{product.name}</td>
                <td className="font-mono">{product.price ?? "—"}</td>
                <td className="font-mono">{product.sku ?? "—"}</td>
                <td>
                  <Link
                    href={`/bots/${botId}/products/${product.id}/edit`}
                    className="font-medium text-accent hover:underline"
                  >
                    Редактировать
                  </Link>
                </td>
                <td>
                  <Button variant="danger" onClick={() => void handleDelete(product.id)}>
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
          className="mt-4"
          onClick={() => void handleLoadMore()}
          disabled={loadingMore}
        >
          {loadingMore ? "Загружаем…" : "Показать ещё"}
        </Button>
      )}
    </>
  );
}
```

- [ ] **Step 4: Run the test file to verify all 9 cases pass**

Run: `npx vitest run components/ProductsTable.test.tsx`
Expected: PASS (9 tests — the original 8 plus the new empty-state case).

- [ ] **Step 5: Rewrite `app/bots/[id]/products/page.tsx`**

Replace the full content of `services/admin-web/app/bots/[id]/products/page.tsx`:

```tsx
import Link from "next/link";
import { notFound } from "next/navigation";
import { ProductsTable } from "@/components/ProductsTable";
import { buttonClasses } from "@/components/ui/Button";
import { fetchBot, fetchProducts } from "@/lib/api";
import { API_INTERNAL_URL, API_PROXY_PATH } from "@/lib/env";

// Совпадает с PRODUCTS_LIST_DEFAULT_LIMIT в services/api/src/api/routers/
// products.py — ProductsTable сравнивает длину полученной страницы с этим
// числом, чтобы понять, есть ли ещё товары ("Показать ещё").
const PRODUCTS_PAGE_SIZE = 100;

export default async function BotProductsPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const bot = await fetchBot(API_INTERNAL_URL, id);
  if (!bot) {
    notFound();
  }
  const products = await fetchProducts(API_INTERNAL_URL, id, { limit: PRODUCTS_PAGE_SIZE });

  return (
    <main>
      <div className="mb-6 flex justify-end">
        <Link href={`/bots/${id}/products/new`} className={buttonClasses()}>
          + Добавить товар
        </Link>
      </div>
      <ProductsTable
        botId={id}
        apiBaseUrl={API_PROXY_PATH}
        products={products}
        pageSize={PRODUCTS_PAGE_SIZE}
      />
    </main>
  );
}
```

Note what's dropped versus the old page: the `← Назад к боту` link and the
`<h1>{bot.name} — товары</h1>` heading — both redundant now that
`app/bots/[id]/layout.tsx` renders the bot's name and a "Товары" tab.

- [ ] **Step 6: Run the full suite and the build**

Run: `npm test`
Expected: full existing suite passes, including the now-9-test
`ProductsTable.test.tsx`.

Run: `npm run build`
Expected: build succeeds.

- [ ] **Step 7: Commit**

```bash
git add services/admin-web/components/ProductsTable.tsx services/admin-web/components/ProductsTable.test.tsx \
  services/admin-web/app/bots/\[id\]/products/page.tsx
git commit -m "feat(admin-web): migrate ProductsTable and its page to the design system"
```

---

### Task 2: `ProductForm` on the design system

**Files:**
- Modify: `services/admin-web/components/ProductForm.tsx`

**Interfaces:**
- Consumes: `Card`, `Input`, `NumberField`, `Textarea`, `Switch`, `Button`
  (existing primitives, unchanged).
- External contract unchanged: every field's accessible name (implicit
  label-wrapping, identical to before), `noValidate` on the `<form>`, every
  `role="alert"`/`role="status"` via `useToast()`, the exact shape of every
  `createProduct`/`updateProduct`/`addProductPhotos`/`deleteProductPhoto`
  call. **No new behavior** — `handleSubmit`, `handleAddPhotos`,
  `handleDeletePhoto`, `toInput`, `initialState`, and every hint
  (`showPriceHint`/`showSkuHint`/`showDescriptionHint`) computation are
  untouched. `ProductForm.test.tsx` must pass with **zero edits**.

- [ ] **Step 1: Confirm the existing test currently passes (baseline)**

Run: `npx vitest run components/ProductForm.test.tsx`
Expected: PASS (16 tests) — baseline before touching the component.

- [ ] **Step 2: Add the primitive imports**

In `services/admin-web/components/ProductForm.tsx`, add these imports
alongside the existing `createProduct`/`useToast` imports (do not
otherwise touch the import block):

```tsx
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { NumberField } from "@/components/ui/NumberField";
import { Switch } from "@/components/ui/Switch";
import { Textarea } from "@/components/ui/Textarea";
```

- [ ] **Step 3: Replace the `return (...)` JSX block only**

Keep everything above `return (` in the `ProductForm` function —
`initialState`, `toInput`, the `FormState` interface, and the entire
function body through `handleDeletePhoto` — byte-identical. Replace only
the JSX:

```tsx
  return (
    // noValidate — та же причина, что и в BotSettingsForm: нативная
    // HTML5-валидация (required/min) тихо блокирует submit ДО нашей проверки.
    <form noValidate onSubmit={(e) => void handleSubmit(e)} className="max-w-xl space-y-5">
      <Card className="space-y-4 p-5">
        <label className="mb-0 block text-sm font-medium text-ink">
          Название
          <Input
            type="text"
            value={state.name}
            onChange={(e) => setState({ ...state, name: e.target.value })}
            className="mt-1.5"
          />
        </label>
        <div>
          <label className="mb-0 block text-sm font-medium text-ink">
            Цена
            <NumberField
              min={0}
              step={0.01}
              value={state.price}
              onChange={(e) => setState({ ...state, price: e.target.value })}
              className="mt-1.5 max-w-xs"
            />
          </label>
          {showPriceHint && <p className="mt-1.5 text-xs text-ink-soft">{clearHint}</p>}
        </div>
        <div>
          <label className="mb-0 block text-sm font-medium text-ink">
            Артикул (SKU)
            <Input
              type="text"
              value={state.sku}
              onChange={(e) => setState({ ...state, sku: e.target.value })}
              className="mt-1.5 max-w-xs"
            />
          </label>
          {showSkuHint && <p className="mt-1.5 text-xs text-ink-soft">{clearHint}</p>}
        </div>
        <div>
          <label className="mb-0 block text-sm font-medium text-ink">
            Описание
            <Textarea
              rows={4}
              value={state.description}
              onChange={(e) => setState({ ...state, description: e.target.value })}
              className="mt-1.5"
            />
          </label>
          {showDescriptionHint && <p className="mt-1.5 text-xs text-ink-soft">{clearHint}</p>}
        </div>
      </Card>

      <Card className="p-5">
        <label className="mb-0 flex items-center gap-2.5 text-sm font-medium text-ink">
          <Switch
            checked={state.displayOverride}
            onChange={(e) => setState({ ...state, displayOverride: e.target.checked })}
          />
          Переопределить вывод для этого товара
        </label>
        {state.displayOverride && (
          <fieldset className="mt-4 space-y-3 border-0 p-0">
            <label className="mb-0 flex items-center gap-2.5 text-sm font-medium text-ink">
              <Switch
                checked={state.showName}
                onChange={(e) => setState({ ...state, showName: e.target.checked })}
              />
              Показывать название
            </label>
            <label className="mb-0 flex items-center gap-2.5 text-sm font-medium text-ink">
              <Switch
                checked={state.showDescription}
                onChange={(e) => setState({ ...state, showDescription: e.target.checked })}
              />
              Показывать описание
            </label>
            <label className="mb-0 flex items-center gap-2.5 text-sm font-medium text-ink">
              <Switch
                checked={state.showPrice}
                onChange={(e) => setState({ ...state, showPrice: e.target.checked })}
              />
              Показывать цену
            </label>
          </fieldset>
        )}
      </Card>

      {!product && (
        <Card className="p-5">
          <label className="mb-0 block text-sm font-medium text-ink">
            Фото
            <input
              type="file"
              multiple
              accept="image/jpeg,image/png,image/webp"
              onChange={(e) => setNewPhotos(e.target.files ? Array.from(e.target.files) : [])}
              className="mt-1.5 block text-sm text-ink-soft file:mr-3 file:rounded-md file:border file:border-border file:bg-surface file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-ink hover:file:border-ink-faint"
            />
          </label>
        </Card>
      )}

      <Button type="submit" disabled={saving}>
        {saving ? "Сохраняем…" : "Сохранить"}
      </Button>

      {product && (
        <Card className="p-5">
          <h2 className="mb-4 text-[15px] font-semibold text-ink">Фото</h2>
          <div className="flex flex-wrap gap-4">
            {photos.map((photo) => (
              <div key={photo.id} className="w-24">
                <img
                  src={productPhotoUrl(apiBaseUrl, botId, product.id, photo.id)}
                  alt="Фото товара"
                  className="h-24 w-24 rounded-md object-cover"
                />
                <Button
                  type="button"
                  variant="secondary"
                  className="mt-2 w-full justify-center"
                  disabled={photoBusy || photos.length <= 1}
                  onClick={() => void handleDeletePhoto(photo.id)}
                >
                  Удалить фото
                </Button>
              </div>
            ))}
          </div>
          <label className="mb-0 mt-4 block text-sm font-medium text-ink">
            Добавить ещё
            <input
              type="file"
              multiple
              accept="image/jpeg,image/png,image/webp"
              disabled={photoBusy}
              onChange={(e) => void handleAddPhotos(e.target.files)}
              className="mt-1.5 block text-sm text-ink-soft file:mr-3 file:rounded-md file:border file:border-border file:bg-surface file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-ink hover:file:border-ink-faint disabled:opacity-60"
            />
          </label>
        </Card>
      )}
    </form>
  );
```

- [ ] **Step 4: Run the test to confirm all 16 cases still pass, unmodified**

Run: `npx vitest run components/ProductForm.test.tsx`
Expected: PASS (16 tests) — same assertions, against the restyled markup.
Pay particular attention to the file-input tests (`fireEvent.change(...,
{ target: { files: [...] } })`) and the display-override checkbox tests —
these exercise the exact `onChange` wiring that must be byte-for-byte
preserved.

- [ ] **Step 5: Commit**

```bash
git add services/admin-web/components/ProductForm.tsx
git commit -m "feat(admin-web): migrate ProductForm to the design system"
```

---

### Task 3: `products/new` and `products/[productId]/edit` page assembly

**Files:**
- Modify: `services/admin-web/app/bots/[id]/products/new/page.tsx`
- Modify: `services/admin-web/app/bots/[id]/products/[productId]/edit/page.tsx`

**Interfaces:**
- Consumes: `ProductForm` (Task 2) — props unchanged.
- No test files exist for either page — the full suite
  (`ProductForm.test.tsx`, unaffected by this task) is the safety net.

- [ ] **Step 1: Rewrite `app/bots/[id]/products/new/page.tsx`**

Replace the full content of `services/admin-web/app/bots/[id]/products/new/page.tsx`:

```tsx
import { notFound } from "next/navigation";
import { ProductForm } from "@/components/ProductForm";
import { fetchBot } from "@/lib/api";
import { API_INTERNAL_URL, API_PROXY_PATH } from "@/lib/env";

export default async function NewProductPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const bot = await fetchBot(API_INTERNAL_URL, id);
  if (!bot) {
    notFound();
  }

  return (
    <main>
      <ProductForm botId={id} apiBaseUrl={API_PROXY_PATH} />
    </main>
  );
}
```

- [ ] **Step 2: Rewrite `app/bots/[id]/products/[productId]/edit/page.tsx`**

Replace the full content of `services/admin-web/app/bots/[id]/products/[productId]/edit/page.tsx`:

```tsx
import { notFound } from "next/navigation";
import { ProductForm } from "@/components/ProductForm";
import { fetchBot, fetchProduct } from "@/lib/api";
import { API_INTERNAL_URL, API_PROXY_PATH } from "@/lib/env";

export default async function EditProductPage({
  params,
}: {
  params: Promise<{ id: string; productId: string }>;
}) {
  const { id, productId } = await params;
  const bot = await fetchBot(API_INTERNAL_URL, id);
  if (!bot) {
    notFound();
  }
  const product = await fetchProduct(API_INTERNAL_URL, id, productId);
  if (!product) {
    notFound();
  }

  return (
    <main>
      <ProductForm botId={id} apiBaseUrl={API_PROXY_PATH} product={product} />
    </main>
  );
}
```

Both drop the `← Назад к товарам` link and their own `<h1>` — redundant
for the same reason as Task 1's list page (the bot-scoped layout already
shows the bot's name and the "Товары" tab).

- [ ] **Step 3: Run the full suite, typecheck, and build**

Run: `npm test`
Expected: full existing suite passes unchanged (this task adds no new
tests).

Run: `npx tsc --noEmit`
Expected: clean.

Run: `npm run build`
Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add services/admin-web/app/bots/\[id\]/products/new/page.tsx \
  services/admin-web/app/bots/\[id\]/products/\[productId\]/edit/page.tsx
git commit -m "feat(admin-web): assemble products new/edit pages on the design system"
```

---

## After this plan

Next screen-group plan per the spec's inventory: documents and blocked
numbers (`DocumentsTable`, `BlockedNumbersTable`).
