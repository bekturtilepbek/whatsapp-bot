# Cabinet Redesign — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `services/admin-web` a real design system (Tailwind CSS v4, design
tokens, a `components/ui/` primitive library) and roll out the two structural
navigation pieces — the sidebar shell and the bot-scoped tab layout — without
touching any individual screen's business logic.

**Architecture:** Tailwind v4's CSS-first `@theme` block turns the spec's color/
font tokens into both native CSS custom properties and Tailwind utility classes
in one place. The existing hand-rolled `globals.css` rules are preserved
verbatim inside `@layer base` (Tailwind's cascade layers make later
`@layer utilities` classes — i.e. every new primitive — win automatically,
so nothing already shipped regresses while unmigrated screens keep their
current, if plain, appearance). A new `components/ui/` library holds every
shared primitive the spec names; screens outside this plan's scope (bots
list, products, settings, etc.) are **not** touched here — they get their own
follow-up plans per the spec's own screen inventory. This plan only rewires
navigation chrome: `AppHeader` becomes `Sidebar`, and a new
`app/bots/[id]/layout.tsx` replaces the current hub-page-of-links with a
shared header + tab strip.

**Tech Stack:** Next.js 15 (App Router, React 19 Server Components), Tailwind
CSS v4 (`tailwindcss` + `@tailwindcss/postcss`, no separate `autoprefixer` —
v4 handles vendor prefixing internally via Lightning CSS), `next/font/google`
(IBM Plex Sans + IBM Plex Mono, self-hosted at build time), vitest +
@testing-library/react (existing test stack, unchanged).

**Spec:** `docs/superpowers/specs/2026-09-13-cabinet-redesign-design.md`

## Global Constraints

- **No dark theme, no mobile-specific layout.** Light only; desktop-first.
  Relative units / flex / grid so nothing literally breaks on a narrow
  viewport, but no mobile nav is built (spec: "Явно вне скоупа").
- **Tokens are the only source of color/font values.** Every new component
  reads Tailwind utility classes derived from the `@theme` block below —
  never a raw hex value in a component file.
- **Exact token values** (from the spec — copy verbatim into `@theme`):
  `ink #1C1B19` · `ink-soft #6F6A62` · `ink-faint #A39C8E` · `canvas #FAF9F6` ·
  `surface #FFFFFF` · `surface-alt #F1EFEA` · `border #E4E0D8` ·
  `sidebar #1B1A17` · `sidebar-ink #EDE9E2` · `sidebar-ink-soft #A39C8E` ·
  `accent #3459B4` · `accent-hover #274783` · `accent-soft #E8EDF8` ·
  `success #1C8A5E` · `warning #B7791F` · `danger #C0362C`.
- **Existing tests are the regression contract.** Every current
  `*.test.tsx` must still pass after this plan (they assert on
  `getByText`/`getByRole`/`href`, not on CSS classes, so this is expected to
  hold — but each task that touches an existing file re-runs `npm test` to
  confirm it, not just the new file's own test).
- **No `Td variant="mono"` or similar over-fitted subcomponent.** Mono
  styling on a numeric/id table column is a plain `className="font-mono"` on
  that `<td>` at the call site — the spec rules this out explicitly as YAGNI.
- **`Switch` renders a real `<input type="checkbox">`** (styled to look like
  a toggle) — no explicit `role="switch"` override, so it keeps the native
  implicit `role="checkbox"` that existing/future tests rely on.
- **Screens are out of scope.** `BotsTable`, `ProductsTable`,
  `BotSettingsForm`, `UsageTable`, `AuditLogTable`, `UsersTable`,
  `DashboardTable`, `DocumentsTable`, `BlockedNumbersTable`, `NewBotForm`,
  `RenameBotForm`, `PromptEditor`, `QrPanel`, `SandboxChat`, and `/login` are
  **not modified** by this plan. They keep rendering plain, unstyled markup
  (inside the new sidebar/canvas chrome) until their own follow-up plans
  migrate them onto `components/ui/`. This is intentional and visible when
  running the app after this plan lands — not a bug to fix here.
- Conventional Commits; every task commits its own working, tested slice.

---

### Task 1: Tailwind v4 + design tokens + fonts

**Files:**
- Modify: `services/admin-web/package.json` (add `tailwindcss`,
  `@tailwindcss/postcss`)
- Create: `services/admin-web/postcss.config.mjs`
- Create: `services/admin-web/lib/fonts.ts`
- Modify: `services/admin-web/app/globals.css`
- Modify: `services/admin-web/app/layout.tsx`

**Interfaces:**
- Produces: `plexSans`, `plexMono` (from `lib/fonts.ts`) — `next/font/google`
  font objects, each exposing `.variable` (a CSS class name string). Every
  later task that needs the sans/mono font families uses Tailwind's
  `font-sans` / `font-mono` utility classes — never imports `plexSans`
  directly.
- Produces: Tailwind utility classes for every token in Global Constraints
  above (e.g. `bg-canvas`, `text-ink-soft`, `border-border`, `bg-accent`,
  `text-success`) — every later task's className strings assume these
  exist.

This task has no dedicated new test file (it's pure build/tooling
infrastructure) — its test is the **existing suite staying green** plus the
app still building.

- [ ] **Step 1: Confirm the current baseline is green**

Run: `npm test` (from `services/admin-web`)
Expected: all existing tests PASS (this is the baseline you must not break).

- [ ] **Step 2: Install Tailwind v4**

```bash
npm install -D tailwindcss@^4.3.3 @tailwindcss/postcss@^4.3.3
```

- [ ] **Step 3: Add the PostCSS config**

Create `services/admin-web/postcss.config.mjs`:

```js
/** @type {import('postcss-load-config').Config} */
const config = {
  plugins: {
    "@tailwindcss/postcss": {},
  },
};

export default config;
```

- [ ] **Step 4: Add the font loader**

Create `services/admin-web/lib/fonts.ts`:

```ts
// next/font/google самохостит файлы шрифтов на билде (без внешнего запроса
// в браузере и без layout shift от системного фолбэка) — единственное место,
// где шрифты объявляются; остальной код обращается к ним только через
// Tailwind-утилиты font-sans/font-mono (см. @theme в globals.css), никогда
// не импортирует plexSans/plexMono напрямую.
import { IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";

export const plexSans = IBM_Plex_Sans({
  subsets: ["latin", "cyrillic"],
  weight: ["400", "500", "600"],
  variable: "--font-plex-sans",
  display: "swap",
});

export const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-plex-mono",
  display: "swap",
});
```

- [ ] **Step 5: Rewrite `globals.css`**

Replace the full content of `services/admin-web/app/globals.css` with:

```css
@import "tailwindcss";

@theme {
  --color-ink: #1c1b19;
  --color-ink-soft: #6f6a62;
  --color-ink-faint: #a39c8e;
  --color-canvas: #faf9f6;
  --color-surface: #ffffff;
  --color-surface-alt: #f1efea;
  --color-border: #e4e0d8;
  --color-sidebar: #1b1a17;
  --color-sidebar-ink: #ede9e2;
  --color-sidebar-ink-soft: #a39c8e;
  --color-accent: #3459b4;
  --color-accent-hover: #274783;
  --color-accent-soft: #e8edf8;
  --color-success: #1c8a5e;
  --color-warning: #b7791f;
  --color-danger: #c0362c;

  --font-sans: var(--font-plex-sans), ui-sans-serif, system-ui, sans-serif;
  --font-mono: var(--font-plex-mono), ui-monospace, monospace;
}

/* Существующие правила ДО этой волны редизайна — сохранены дословно и
 * обёрнуты в @layer base, а не удалены: Tailwind-слои идут base < components
 * < utilities, поэтому любой новый примитив (@layer utilities, то есть
 * className-утилиты на компонентах components/ui/) автоматически побеждает
 * эти правила в каскаде, а ещё не мигрированные экраны (BotsTable,
 * ProductsTable и т.д. — см. Global Constraints плана) продолжают выглядеть
 * ровно как раньше. Правила удаляются целиком только последним таском самой
 * последней волны редизайна экранов, когда ни один <table>/<button> без
 * className их больше не использует. */
@layer base {
  body {
    font-family: system-ui, sans-serif;
    margin: 2rem;
    color: #1a1a1a;
  }

  table {
    border-collapse: collapse;
    width: 100%;
  }

  th,
  td {
    text-align: left;
    padding: 0.5rem 1rem;
    border-bottom: 1px solid #ddd;
  }

  button {
    padding: 0.5rem 1rem;
    cursor: pointer;
  }

  textarea {
    width: 100%;
    font-family: inherit;
    font-size: 1rem;
    padding: 0.5rem;
    box-sizing: border-box;
  }

  section {
    margin-bottom: 2rem;
  }

  ul {
    list-style: none;
    padding: 0;
  }

  li {
    padding: 0.5rem 0;
    border-bottom: 1px solid #ddd;
  }

  form label {
    display: block;
    margin-bottom: 1rem;
  }

  form input[type="number"],
  form input[type="text"] {
    display: block;
    margin-top: 0.25rem;
    padding: 0.4rem;
    font-size: 1rem;
  }

  form input[type="checkbox"] {
    margin-right: 0.5rem;
  }
}
```

- [ ] **Step 6: Wire the fonts into the root layout**

In `services/admin-web/app/layout.tsx`, add the import and apply the font
variables to the `<html>` element (leave everything else in the file
untouched for this task — `AppHeader`/`Sidebar` swap is Task 8):

```tsx
import { plexMono, plexSans } from "@/lib/fonts";
```

Change the `<html>` tag to:

```tsx
    <html lang="ru" className={`${plexSans.variable} ${plexMono.variable}`}>
```

- [ ] **Step 7: Verify the app still builds and tests still pass**

Run: `npm run build` (from `services/admin-web`)
Expected: build succeeds with no errors.

Run: `npm test`
Expected: same tests pass as in Step 1 — no regressions.

- [ ] **Step 8: Commit**

```bash
git add services/admin-web/package.json services/admin-web/package-lock.json \
  services/admin-web/postcss.config.mjs services/admin-web/lib/fonts.ts \
  services/admin-web/app/globals.css services/admin-web/app/layout.tsx
git commit -m "feat(admin-web): add Tailwind v4, design tokens and fonts"
```

---

### Task 2: `Button` primitive

**Files:**
- Create: `services/admin-web/components/ui/Button.tsx`
- Test: `services/admin-web/components/ui/Button.test.tsx`

**Interfaces:**
- Consumes: Tailwind token utilities from Task 1 (`bg-accent`,
  `text-danger`, etc.).
- Produces: `Button` — a drop-in replacement for a bare `<button>`. Props:
  `variant?: "primary" | "secondary" | "danger"` (default `"primary"`) plus
  every native `ButtonHTMLAttributes<HTMLButtonElement>` (so `type`,
  `onClick`, `disabled`, `className` all pass through unchanged — later
  screen-migration plans rely on this passthrough).

- [ ] **Step 1: Write the failing test**

Create `services/admin-web/components/ui/Button.test.tsx`:

```tsx
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Button } from "@/components/ui/Button";

it("renders its children as the accessible name", () => {
  render(<Button>Сохранить</Button>);
  expect(screen.getByRole("button", { name: "Сохранить" })).toBeInTheDocument();
});

it("calls onClick when clicked", () => {
  const onClick = vi.fn();
  render(<Button onClick={onClick}>Сохранить</Button>);
  fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
  expect(onClick).toHaveBeenCalledOnce();
});

it("does not fire onClick when disabled", () => {
  const onClick = vi.fn();
  render(
    <Button onClick={onClick} disabled>
      Сохранить
    </Button>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
  expect(onClick).not.toHaveBeenCalled();
});

it("forwards the native type attribute", () => {
  render(<Button type="submit">Отправить</Button>);
  expect(screen.getByRole("button", { name: "Отправить" })).toHaveAttribute("type", "submit");
});

it("renders every variant without crashing", () => {
  const { rerender } = render(<Button variant="primary">A</Button>);
  expect(screen.getByRole("button")).toBeInTheDocument();
  rerender(<Button variant="secondary">A</Button>);
  expect(screen.getByRole("button")).toBeInTheDocument();
  rerender(<Button variant="danger">A</Button>);
  expect(screen.getByRole("button")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npx vitest run components/ui/Button.test.tsx`
Expected: FAIL — `Cannot find module '@/components/ui/Button'`.

- [ ] **Step 3: Implement `Button`**

Create `services/admin-web/components/ui/Button.tsx`:

```tsx
import type { ButtonHTMLAttributes } from "react";

type ButtonVariant = "primary" | "secondary" | "danger";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
}

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary: "bg-accent text-white hover:bg-accent-hover",
  secondary: "bg-surface text-ink border border-border hover:border-ink-faint",
  danger: "bg-surface text-danger border border-danger hover:bg-danger/5",
};

export function Button({ variant = "primary", className = "", ...props }: ButtonProps) {
  return (
    <button
      className={`inline-flex items-center gap-2 rounded-md px-3.5 py-2 text-sm font-medium leading-tight transition-colors disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2 ${VARIANT_CLASSES[variant]} ${className}`}
      {...props}
    />
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `npx vitest run components/ui/Button.test.tsx`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add services/admin-web/components/ui/Button.tsx services/admin-web/components/ui/Button.test.tsx
git commit -m "feat(admin-web): add Button primitive"
```

---

### Task 3: Form field primitives (`Input`, `Textarea`, `NumberField`, `Select`, `Switch`)

**Files:**
- Create: `services/admin-web/components/ui/Input.tsx`
- Create: `services/admin-web/components/ui/Textarea.tsx`
- Create: `services/admin-web/components/ui/NumberField.tsx`
- Create: `services/admin-web/components/ui/Select.tsx`
- Create: `services/admin-web/components/ui/Switch.tsx`
- Test: `services/admin-web/components/ui/Input.test.tsx`
- Test: `services/admin-web/components/ui/Textarea.test.tsx`
- Test: `services/admin-web/components/ui/NumberField.test.tsx`
- Test: `services/admin-web/components/ui/Select.test.tsx`
- Test: `services/admin-web/components/ui/Switch.test.tsx`

**Interfaces:**
- Produces: `Input`, `Textarea` — thin styled wrappers over the native
  elements, forwarding every native attribute plus `className`.
- Produces: `NumberField` — forwards to `Input` with `type="number"` fixed
  (props type excludes `type`).
- Produces: `Select` — styled wrapper over native `<select>`, forwards
  `children` (the `<option>`s) and every native attribute.
- Produces: `Switch` — styled `<input type="checkbox">` (native implicit
  `role="checkbox"`, per Global Constraints — no `role="switch"` override).

- [ ] **Step 1: Write the failing tests**

Create `services/admin-web/components/ui/Input.test.tsx`:

```tsx
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Input } from "@/components/ui/Input";

it("renders with the given placeholder and forwards typing", () => {
  const onChange = vi.fn();
  render(<Input placeholder="Название" onChange={onChange} />);
  const field = screen.getByPlaceholderText("Название");
  fireEvent.change(field, { target: { value: "Кофейня" } });
  expect(onChange).toHaveBeenCalledOnce();
});

it("forwards disabled and value", () => {
  render(<Input value="Кофейня" disabled onChange={() => {}} />);
  const field = screen.getByDisplayValue("Кофейня");
  expect(field).toBeDisabled();
});
```

Create `services/admin-web/components/ui/Textarea.test.tsx`:

```tsx
import { expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Textarea } from "@/components/ui/Textarea";

it("renders with the given placeholder and forwards typing", () => {
  const onChange = vi.fn();
  render(<Textarea placeholder="Промпт" onChange={onChange} />);
  const field = screen.getByPlaceholderText("Промпт");
  fireEvent.change(field, { target: { value: "Ты — помощник" } });
  expect(onChange).toHaveBeenCalledOnce();
});
```

Create `services/admin-web/components/ui/NumberField.test.tsx`:

```tsx
import { expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { NumberField } from "@/components/ui/NumberField";

it("renders as a native number input", () => {
  render(<NumberField aria-label="Таймаут батчинга" value={1} onChange={() => {}} />);
  const field = screen.getByLabelText("Таймаут батчинга");
  expect(field).toHaveAttribute("type", "number");
});
```

Create `services/admin-web/components/ui/Select.test.tsx`:

```tsx
import { expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Select } from "@/components/ui/Select";

it("renders its options and forwards selection changes", () => {
  const onChange = vi.fn();
  render(
    <Select aria-label="Период" onChange={onChange}>
      <option value="7d">7 дней</option>
      <option value="30d">30 дней</option>
    </Select>,
  );
  const field = screen.getByLabelText("Период");
  fireEvent.change(field, { target: { value: "30d" } });
  expect(onChange).toHaveBeenCalledOnce();
  expect(screen.getByRole("option", { name: "30 дней" })).toBeInTheDocument();
});
```

Create `services/admin-web/components/ui/Switch.test.tsx`:

```tsx
import { expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Switch } from "@/components/ui/Switch";

it("renders as a checkbox (native implicit role, not an explicit role override)", () => {
  render(<Switch aria-label="Напоминание" checked={false} onChange={() => {}} />);
  const field = screen.getByRole("checkbox", { name: "Напоминание" });
  expect(field).not.toBeChecked();
});

it("forwards toggle changes", () => {
  const onChange = vi.fn();
  render(<Switch aria-label="Напоминание" checked={false} onChange={onChange} />);
  fireEvent.click(screen.getByRole("checkbox", { name: "Напоминание" }));
  expect(onChange).toHaveBeenCalledOnce();
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npx vitest run components/ui/Input.test.tsx components/ui/Textarea.test.tsx components/ui/NumberField.test.tsx components/ui/Select.test.tsx components/ui/Switch.test.tsx`
Expected: FAIL — none of the modules exist yet.

- [ ] **Step 3: Implement the primitives**

Create `services/admin-web/components/ui/Input.tsx`:

```tsx
import type { InputHTMLAttributes } from "react";

type InputProps = InputHTMLAttributes<HTMLInputElement>;

export function Input({ className = "", ...props }: InputProps) {
  return (
    <input
      className={`w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-1 disabled:cursor-not-allowed disabled:opacity-60 ${className}`}
      {...props}
    />
  );
}
```

Create `services/admin-web/components/ui/Textarea.tsx`:

```tsx
import type { TextareaHTMLAttributes } from "react";

type TextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement>;

export function Textarea({ className = "", ...props }: TextareaProps) {
  return (
    <textarea
      className={`w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-1 disabled:cursor-not-allowed disabled:opacity-60 ${className}`}
      {...props}
    />
  );
}
```

Create `services/admin-web/components/ui/NumberField.tsx`:

```tsx
import type { InputHTMLAttributes } from "react";
import { Input } from "@/components/ui/Input";

type NumberFieldProps = Omit<InputHTMLAttributes<HTMLInputElement>, "type">;

export function NumberField(props: NumberFieldProps) {
  return <Input type="number" {...props} />;
}
```

Create `services/admin-web/components/ui/Select.tsx`:

```tsx
import type { SelectHTMLAttributes } from "react";

type SelectProps = SelectHTMLAttributes<HTMLSelectElement>;

export function Select({ className = "", children, ...props }: SelectProps) {
  return (
    <select
      className={`rounded-md border border-border bg-surface px-3 py-2 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-1 ${className}`}
      {...props}
    >
      {children}
    </select>
  );
}
```

Create `services/admin-web/components/ui/Switch.tsx`:

```tsx
import type { InputHTMLAttributes } from "react";

// Настоящий <input type="checkbox"> под стилизацией «тумблера» — сохраняет
// нативный implicit role="checkbox" (не role="switch"): существующие и
// будущие тесты форм ищут переключатели через getByRole("checkbox"), явный
// role здесь его бы перекрыл (см. Global Constraints плана).
type SwitchProps = Omit<InputHTMLAttributes<HTMLInputElement>, "type">;

export function Switch({ className = "", ...props }: SwitchProps) {
  return (
    <input
      type="checkbox"
      className={`relative h-5 w-9 shrink-0 cursor-pointer appearance-none rounded-full bg-border transition-colors before:absolute before:left-0.5 before:top-0.5 before:h-4 before:w-4 before:rounded-full before:bg-white before:transition-transform checked:bg-accent checked:before:translate-x-4 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-60 ${className}`}
      {...props}
    />
  );
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npx vitest run components/ui/Input.test.tsx components/ui/Textarea.test.tsx components/ui/NumberField.test.tsx components/ui/Select.test.tsx components/ui/Switch.test.tsx`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add services/admin-web/components/ui/Input.tsx services/admin-web/components/ui/Input.test.tsx \
  services/admin-web/components/ui/Textarea.tsx services/admin-web/components/ui/Textarea.test.tsx \
  services/admin-web/components/ui/NumberField.tsx services/admin-web/components/ui/NumberField.test.tsx \
  services/admin-web/components/ui/Select.tsx services/admin-web/components/ui/Select.test.tsx \
  services/admin-web/components/ui/Switch.tsx services/admin-web/components/ui/Switch.test.tsx
git commit -m "feat(admin-web): add form field primitives (Input, Textarea, NumberField, Select, Switch)"
```

---

### Task 4: Layout primitives (`Card`, `Badge`, `PageHeader`, `EmptyState`)

**Files:**
- Create: `services/admin-web/components/ui/Card.tsx`
- Create: `services/admin-web/components/ui/Badge.tsx`
- Create: `services/admin-web/components/ui/PageHeader.tsx`
- Create: `services/admin-web/components/ui/EmptyState.tsx`
- Test: `services/admin-web/components/ui/Card.test.tsx`
- Test: `services/admin-web/components/ui/Badge.test.tsx`
- Test: `services/admin-web/components/ui/PageHeader.test.tsx`
- Test: `services/admin-web/components/ui/EmptyState.test.tsx`

**Interfaces:**
- Produces: `Card` — `<div>` wrapper (surface + border + radius), forwards
  `className` and every native `div` attribute (`children` included).
- Produces: `Badge` — `variant?: "owner" | "paused" | "neutral"` (default
  `"neutral"`), forwards `children`/`className`.
- Produces: `PageHeader` — `{ title: string; subtitle?: string; action?: ReactNode }`.
  A future screen task's `<h1>` + manual button row collapses into this.
- Produces: `EmptyState` — `{ title: string; description?: string; action?: ReactNode }`.

- [ ] **Step 1: Write the failing tests**

Create `services/admin-web/components/ui/Card.test.tsx`:

```tsx
import { expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Card } from "@/components/ui/Card";

it("renders its children", () => {
  render(<Card>Содержимое карточки</Card>);
  expect(screen.getByText("Содержимое карточки")).toBeInTheDocument();
});

it("merges a caller className with its own", () => {
  render(<Card className="custom-class">X</Card>);
  expect(screen.getByText("X")).toHaveClass("custom-class");
});
```

Create `services/admin-web/components/ui/Badge.test.tsx`:

```tsx
import { expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Badge } from "@/components/ui/Badge";

it("renders its children for every variant", () => {
  const { rerender } = render(<Badge variant="owner">owner</Badge>);
  expect(screen.getByText("owner")).toBeInTheDocument();
  rerender(<Badge variant="paused">на паузе</Badge>);
  expect(screen.getByText("на паузе")).toBeInTheDocument();
  rerender(<Badge>нейтральный</Badge>);
  expect(screen.getByText("нейтральный")).toBeInTheDocument();
});
```

Create `services/admin-web/components/ui/PageHeader.test.tsx`:

```tsx
import { expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { PageHeader } from "@/components/ui/PageHeader";

it("renders the title as a heading", () => {
  render(<PageHeader title="Боты" />);
  expect(screen.getByRole("heading", { name: "Боты" })).toBeInTheDocument();
});

it("renders an optional subtitle and action", () => {
  render(<PageHeader title="Боты" subtitle="5 ботов" action={<button>Добавить</button>} />);
  expect(screen.getByText("5 ботов")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Добавить" })).toBeInTheDocument();
});

it("omits the subtitle element when none is given", () => {
  render(<PageHeader title="Боты" />);
  expect(screen.queryByText("5 ботов")).not.toBeInTheDocument();
});
```

Create `services/admin-web/components/ui/EmptyState.test.tsx`:

```tsx
import { expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { EmptyState } from "@/components/ui/EmptyState";

it("renders the title, description and action", () => {
  render(
    <EmptyState
      title="Товаров пока нет"
      description="Добавьте первый товар"
      action={<button>Добавить товар</button>}
    />,
  );
  expect(screen.getByText("Товаров пока нет")).toBeInTheDocument();
  expect(screen.getByText("Добавьте первый товар")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Добавить товар" })).toBeInTheDocument();
});

it("omits description and action when not given", () => {
  render(<EmptyState title="Товаров пока нет" />);
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npx vitest run components/ui/Card.test.tsx components/ui/Badge.test.tsx components/ui/PageHeader.test.tsx components/ui/EmptyState.test.tsx`
Expected: FAIL — none of the modules exist yet.

- [ ] **Step 3: Implement the primitives**

Create `services/admin-web/components/ui/Card.tsx`:

```tsx
import type { HTMLAttributes } from "react";

type CardProps = HTMLAttributes<HTMLDivElement>;

export function Card({ className = "", ...props }: CardProps) {
  return <div className={`rounded-lg border border-border bg-surface ${className}`} {...props} />;
}
```

Create `services/admin-web/components/ui/Badge.tsx`:

```tsx
import type { HTMLAttributes } from "react";

type BadgeVariant = "owner" | "paused" | "neutral";

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
}

const BADGE_VARIANT_CLASSES: Record<BadgeVariant, string> = {
  owner: "bg-accent-soft text-accent",
  paused: "bg-warning/15 text-warning",
  neutral: "bg-surface-alt text-ink-soft",
};

export function Badge({ variant = "neutral", className = "", ...props }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${BADGE_VARIANT_CLASSES[variant]} ${className}`}
      {...props}
    />
  );
}
```

Create `services/admin-web/components/ui/PageHeader.tsx`:

```tsx
import type { ReactNode } from "react";

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  action?: ReactNode;
}

export function PageHeader({ title, subtitle, action }: PageHeaderProps) {
  return (
    <div className="mb-6 flex items-start justify-between gap-4">
      <div>
        <h1 className="text-xl font-semibold text-ink">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-ink-soft">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}
```

Create `services/admin-web/components/ui/EmptyState.tsx`:

```tsx
import type { ReactNode } from "react";

interface EmptyStateProps {
  title: string;
  description?: string;
  action?: ReactNode;
}

export function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <div className="rounded-lg border border-dashed border-border px-6 py-12 text-center">
      <h3 className="text-sm font-semibold text-ink">{title}</h3>
      {description && <p className="mt-1.5 text-sm text-ink-soft">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npx vitest run components/ui/Card.test.tsx components/ui/Badge.test.tsx components/ui/PageHeader.test.tsx components/ui/EmptyState.test.tsx`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add services/admin-web/components/ui/Card.tsx services/admin-web/components/ui/Card.test.tsx \
  services/admin-web/components/ui/Badge.tsx services/admin-web/components/ui/Badge.test.tsx \
  services/admin-web/components/ui/PageHeader.tsx services/admin-web/components/ui/PageHeader.test.tsx \
  services/admin-web/components/ui/EmptyState.tsx services/admin-web/components/ui/EmptyState.test.tsx
git commit -m "feat(admin-web): add Card, Badge, PageHeader, EmptyState primitives"
```

---

### Task 5: `StatusPulse` (signature element) + `Table`

**Files:**
- Create: `services/admin-web/components/ui/StatusPulse.tsx`
- Create: `services/admin-web/components/ui/Table.tsx`
- Test: `services/admin-web/components/ui/StatusPulse.test.tsx`
- Test: `services/admin-web/components/ui/Table.test.tsx`

**Interfaces:**
- Produces: `StatusPulse` — `{ status: "connected" | "pending" | "disconnected" }`.
  This is a **normalized** three-way status; a future screen task that
  consumes the raw `Bot.status`/`Bot.linked_at` fields (`lib/api.ts`) is
  responsible for mapping to one of these three values before rendering —
  `StatusPulse` itself never sees the raw backend string. `"connected"` gets
  an animated ring (Tailwind's built-in `animate-ping`, suppressed via the
  built-in `motion-reduce:` variant — no hand-written `@keyframes` needed);
  `"pending"`/`"disconnected"` render a static dot.
- Produces: `Table` — `{ children: ReactNode }`. A styled wrapper: the
  caller still writes a plain `<table><thead>…</thead><tbody>…</tbody></table>`
  exactly as today (existing screen tests query by text/role inside it, so
  this passthrough shape must not change), and `Table` applies every
  header/row/border/hover style via Tailwind's descendant-selector variants
  (`[&_th]:…`) on its own wrapping `<div>` — no `Th`/`Td` subcomponents.

- [ ] **Step 1: Write the failing tests**

Create `services/admin-web/components/ui/StatusPulse.test.tsx`:

```tsx
import { expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusPulse } from "@/components/ui/StatusPulse";

it("shows the Russian label for each status", () => {
  const { rerender } = render(<StatusPulse status="connected" />);
  expect(screen.getByText("Подключён")).toBeInTheDocument();
  rerender(<StatusPulse status="pending" />);
  expect(screen.getByText("Ждёт QR")).toBeInTheDocument();
  rerender(<StatusPulse status="disconnected" />);
  expect(screen.getByText("Не подключён")).toBeInTheDocument();
});
```

Create `services/admin-web/components/ui/Table.test.tsx`:

```tsx
import { expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Table } from "@/components/ui/Table";

it("renders the wrapped table structure unchanged", () => {
  render(
    <Table>
      <table>
        <thead>
          <tr>
            <th>Имя</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Кофейня</td>
          </tr>
        </tbody>
      </table>
    </Table>,
  );
  expect(screen.getByRole("table")).toBeInTheDocument();
  expect(screen.getByRole("columnheader", { name: "Имя" })).toBeInTheDocument();
  expect(screen.getByRole("cell", { name: "Кофейня" })).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npx vitest run components/ui/StatusPulse.test.tsx components/ui/Table.test.tsx`
Expected: FAIL — neither module exists yet.

- [ ] **Step 3: Implement the primitives**

Create `services/admin-web/components/ui/StatusPulse.tsx`:

```tsx
export type BotConnectionStatus = "connected" | "pending" | "disconnected";

interface StatusPulseProps {
  status: BotConnectionStatus;
}

interface StatusConfig {
  label: string;
  dotClass: string;
  labelClass: string;
  animated: boolean;
}

const STATUS_CONFIG: Record<BotConnectionStatus, StatusConfig> = {
  connected: { label: "Подключён", dotClass: "bg-success", labelClass: "text-success", animated: true },
  pending: { label: "Ждёт QR", dotClass: "bg-warning", labelClass: "text-warning", animated: false },
  disconnected: {
    label: "Не подключён",
    dotClass: "bg-ink-faint",
    labelClass: "text-ink-soft",
    animated: false,
  },
};

export function StatusPulse({ status }: StatusPulseProps) {
  const config = STATUS_CONFIG[status];
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span className={`relative inline-flex h-2 w-2 rounded-full ${config.dotClass}`}>
        {config.animated && (
          <span
            className={`absolute -inset-1 rounded-full opacity-60 motion-reduce:hidden ${config.dotClass} animate-ping`}
          />
        )}
      </span>
      <span className={config.labelClass}>{config.label}</span>
    </span>
  );
}
```

Create `services/admin-web/components/ui/Table.tsx`:

```tsx
import type { ReactNode } from "react";

interface TableProps {
  children: ReactNode;
}

const WRAPPER_CLASSES = [
  "overflow-x-auto rounded-lg border border-border bg-surface",
  "[&_table]:w-full [&_table]:border-collapse",
  "[&_th]:border-b [&_th]:border-border [&_th]:bg-surface-alt [&_th]:px-4 [&_th]:py-2.5",
  "[&_th]:text-left [&_th]:text-[11px] [&_th]:font-semibold [&_th]:uppercase",
  "[&_th]:tracking-wide [&_th]:text-ink-soft",
  "[&_td]:border-b [&_td]:border-border [&_td]:px-4 [&_td]:py-3 [&_td]:text-sm [&_td]:align-middle",
  "[&_tbody_tr:last-child_td]:border-b-0",
  "[&_tbody_tr:hover]:bg-surface-alt",
].join(" ");

export function Table({ children }: TableProps) {
  return <div className={WRAPPER_CLASSES}>{children}</div>;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npx vitest run components/ui/StatusPulse.test.tsx components/ui/Table.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add services/admin-web/components/ui/StatusPulse.tsx services/admin-web/components/ui/StatusPulse.test.tsx \
  services/admin-web/components/ui/Table.tsx services/admin-web/components/ui/Table.test.tsx
git commit -m "feat(admin-web): add StatusPulse and Table primitives"
```

---

### Task 6: `Tabs` / `TabLink`

**Files:**
- Create: `services/admin-web/components/ui/Tabs.tsx`
- Create: `services/admin-web/components/ui/TabLink.tsx`
- Test: `services/admin-web/components/ui/TabLink.test.tsx`

**Interfaces:**
- Produces: `Tabs` — `{ children: ReactNode }`, a `<nav>` wrapper laying its
  `TabLink` children out horizontally with a bottom border.
- Produces: `TabLink` — `{ href: string; children: ReactNode; exact?: boolean }`
  (default `exact: true`). Client component (`usePathname`). Sets
  `aria-current="page"` when active: exact string match against `href` when
  `exact` is true, `pathname.startsWith(href)` otherwise. Task 9's bot layout
  uses `exact={false}` for every tab except "Обзор" (`/bots/[id]` itself
  would otherwise also match every one of its own sub-paths).

- [ ] **Step 1: Write the failing test**

Create `services/admin-web/components/ui/TabLink.test.tsx`:

```tsx
import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { TabLink } from "@/components/ui/TabLink";

vi.mock("next/navigation", () => ({
  usePathname: vi.fn(),
}));

import { usePathname } from "next/navigation";
const mockedUsePathname = vi.mocked(usePathname);

it("marks the tab active with aria-current on an exact path match", () => {
  mockedUsePathname.mockReturnValue("/bots/1");
  render(<TabLink href="/bots/1">Обзор</TabLink>);
  expect(screen.getByRole("link", { name: "Обзор" })).toHaveAttribute("aria-current", "page");
});

it("does not mark the tab active on a different path", () => {
  mockedUsePathname.mockReturnValue("/bots/1/settings");
  render(<TabLink href="/bots/1">Обзор</TabLink>);
  expect(screen.getByRole("link", { name: "Обзор" })).not.toHaveAttribute("aria-current");
});

it("matches by prefix when exact is false", () => {
  mockedUsePathname.mockReturnValue("/bots/1/settings");
  render(
    <TabLink href="/bots/1/settings" exact={false}>
      Настройки
    </TabLink>,
  );
  expect(screen.getByRole("link", { name: "Настройки" })).toHaveAttribute("aria-current", "page");
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npx vitest run components/ui/TabLink.test.tsx`
Expected: FAIL — module doesn't exist yet.

- [ ] **Step 3: Implement `Tabs` and `TabLink`**

Create `services/admin-web/components/ui/Tabs.tsx`:

```tsx
import type { ReactNode } from "react";

interface TabsProps {
  children: ReactNode;
}

export function Tabs({ children }: TabsProps) {
  return <nav className="mb-6 flex gap-6 border-b border-border">{children}</nav>;
}
```

Create `services/admin-web/components/ui/TabLink.tsx`:

```tsx
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

interface TabLinkProps {
  href: string;
  children: ReactNode;
  /** Точное совпадение по умолчанию — иначе "/bots/1" (вкладка «Обзор»)
   * подсвечивалась бы активной и на "/bots/1/settings". */
  exact?: boolean;
}

export function TabLink({ href, children, exact = true }: TabLinkProps) {
  const pathname = usePathname();
  const isActive = exact ? pathname === href : pathname.startsWith(href);
  return (
    <Link
      href={href}
      aria-current={isActive ? "page" : undefined}
      className={`-mb-px border-b-2 px-1 pb-3 text-sm ${
        isActive ? "border-accent font-medium text-ink" : "border-transparent text-ink-soft hover:text-ink"
      }`}
    >
      {children}
    </Link>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `npx vitest run components/ui/TabLink.test.tsx`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add services/admin-web/components/ui/Tabs.tsx services/admin-web/components/ui/TabLink.tsx \
  services/admin-web/components/ui/TabLink.test.tsx
git commit -m "feat(admin-web): add Tabs and TabLink primitives"
```

---

### Task 7: Restyle `ToastProvider` on tokens

**Files:**
- Modify: `services/admin-web/components/ToastProvider.tsx`

**Interfaces:**
- Consumes: Tailwind token utilities from Task 1.
- Produces: unchanged — `useToast()` (`showError`/`showSuccess`),
  `role="alert"`/`role="status"`, `aria-label="Закрыть уведомление"`. The
  existing `ToastProvider.test.tsx` is the contract: it must pass with zero
  edits.

- [ ] **Step 1: Confirm the existing test currently passes**

Run: `npx vitest run components/ToastProvider.test.tsx`
Expected: PASS (baseline, before any edit).

- [ ] **Step 2: Replace the inline styles with token-based classes**

In `services/admin-web/components/ToastProvider.tsx`, replace the returned
JSX inside `ToastProvider` (the `<div>` holding the toast stack and each
toast's `<div>`/`<button>`) — keep every prop other than `style` identical
(`role`, `key`, `onClick`, `aria-label`, the text content):

```tsx
      <div className="fixed bottom-4 right-4 z-[1000] flex flex-col gap-2">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            role={toast.kind === "error" ? "alert" : "status"}
            className={`flex max-w-[24rem] items-center gap-3 rounded-lg border-l-[3px] bg-surface px-4 py-3 text-sm text-ink shadow-md ${
              toast.kind === "error" ? "border-l-danger" : "border-l-success"
            }`}
          >
            <span>{toast.message}</span>
            <button
              type="button"
              aria-label="Закрыть уведомление"
              onClick={() => removeToast(toast.id)}
              className="ml-auto text-base text-ink-soft hover:text-ink"
            >
              ×
            </button>
          </div>
        ))}
      </div>
```

- [ ] **Step 3: Run the test again to confirm it still passes**

Run: `npx vitest run components/ToastProvider.test.tsx`
Expected: PASS — same assertions, now against the restyled markup.

- [ ] **Step 4: Commit**

```bash
git add services/admin-web/components/ToastProvider.tsx
git commit -m "refactor(admin-web): restyle ToastProvider on design tokens"
```

---

### Task 8: Sidebar navigation

**Files:**
- Create: `services/admin-web/components/Sidebar.tsx`
- Delete: `services/admin-web/components/AppHeader.tsx`
- Modify: `services/admin-web/app/layout.tsx`
- Modify: `services/admin-web/lib/currentUser.ts` (one comment reference)
- Test: `services/admin-web/components/Sidebar.test.tsx`

**Interfaces:**
- Consumes: `fetchCurrentUser` (`lib/currentUser.ts`, unchanged), `logout`
  (`app/login/actions.ts`, unchanged).
- Produces: `Sidebar` — async Server Component, same data source and same
  owner-only visibility rule as the old `AppHeader`, replacing it 1:1 in
  `app/layout.tsx`. Renders `null` when there is no logged-in user (same as
  before), so `/login` renders with no sidebar column automatically — no
  route-specific special-casing needed.

- [ ] **Step 1: Confirm nothing else imports `AppHeader` before deleting it**

Run: `grep -rn "AppHeader" services/admin-web --include=*.tsx --include=*.ts`
Expected: only `services/admin-web/components/AppHeader.tsx` itself,
`services/admin-web/app/layout.tsx` (Step 3 rewrites it), and a comment
mention in `services/admin-web/lib/currentUser.ts` (Step 4 rewrites it).

- [ ] **Step 2: Write the failing test**

Create `services/admin-web/components/Sidebar.test.tsx`:

```tsx
import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { Sidebar } from "@/components/Sidebar";
import { fetchCurrentUser } from "@/lib/currentUser";

vi.mock("@/lib/currentUser", () => ({
  fetchCurrentUser: vi.fn(),
}));
vi.mock("@/app/login/actions", () => ({
  logout: vi.fn(),
}));

const mockedFetchCurrentUser = vi.mocked(fetchCurrentUser);

it("renders nothing when there is no logged-in user", async () => {
  mockedFetchCurrentUser.mockResolvedValue(null);
  const { container } = render(await Sidebar());
  expect(container).toBeEmptyDOMElement();
});

it("shows only the Боты link and the user's email for a non-owner", async () => {
  mockedFetchCurrentUser.mockResolvedValue({ email: "client@example.com", is_platform_owner: false });
  render(await Sidebar());
  expect(screen.getByRole("link", { name: "Боты" })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Дашборд" })).not.toBeInTheDocument();
  expect(screen.getByText("client@example.com")).toBeInTheDocument();
});

it("shows the platform-owner navigation group for an owner", async () => {
  mockedFetchCurrentUser.mockResolvedValue({ email: "owner@example.com", is_platform_owner: true });
  render(await Sidebar());
  expect(screen.getByRole("link", { name: "Дашборд" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Пользователи" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Аудит-лог" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Расходы" })).toBeInTheDocument();
});
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `npx vitest run components/Sidebar.test.tsx`
Expected: FAIL — module doesn't exist yet.

- [ ] **Step 4: Implement `Sidebar` and delete `AppHeader`**

Create `services/admin-web/components/Sidebar.tsx`:

```tsx
import Link from "next/link";
import { logout } from "@/app/login/actions";
import { fetchCurrentUser } from "@/lib/currentUser";

const NAV_LINK_CLASSES = "rounded-md px-2.5 py-2 text-sm hover:bg-white/5 hover:text-sidebar-ink";

export async function Sidebar() {
  const user = await fetchCurrentUser();
  if (!user) return null;

  return (
    <aside className="flex h-screen w-[232px] shrink-0 flex-col bg-sidebar px-3.5 py-5 text-sidebar-ink-soft">
      <div className="mb-6 flex items-center gap-2 px-2">
        <span className="flex h-6 w-6 items-center justify-center rounded-md bg-accent text-xs font-semibold text-white">
          Б
        </span>
        <span className="text-sm font-semibold text-sidebar-ink">Платформа ботов</span>
      </div>

      <nav className="flex flex-col gap-0.5">
        <Link href="/bots" className={NAV_LINK_CLASSES}>
          Боты
        </Link>
      </nav>

      {user.is_platform_owner && (
        <nav className="mt-5 flex flex-col gap-0.5">
          <div className="px-2.5 pb-1.5 text-[10.5px] uppercase tracking-wide text-sidebar-ink-soft">
            Платформа
          </div>
          <Link href="/dashboard" className={NAV_LINK_CLASSES}>
            Дашборд
          </Link>
          <Link href="/users" className={NAV_LINK_CLASSES}>
            Пользователи
          </Link>
          <Link href="/audit-log" className={NAV_LINK_CLASSES}>
            Аудит-лог
          </Link>
          <Link href="/usage" className={NAV_LINK_CLASSES}>
            Расходы
          </Link>
        </nav>
      )}

      <div className="mt-auto flex items-center gap-2 border-t border-white/10 pt-3.5">
        <span className="min-w-0 flex-1 truncate text-xs text-sidebar-ink-soft">{user.email}</span>
        <form action={logout}>
          <button type="submit" className="text-xs text-sidebar-ink-soft hover:text-sidebar-ink">
            Выйти
          </button>
        </form>
      </div>
    </aside>
  );
}
```

Delete `services/admin-web/components/AppHeader.tsx`.

- [ ] **Step 5: Rewrite `app/layout.tsx`**

Replace the full content of `services/admin-web/app/layout.tsx` with:

```tsx
import type { ReactNode } from "react";
import { Sidebar } from "@/components/Sidebar";
import { ToastProvider } from "@/components/ToastProvider";
import { plexMono, plexSans } from "@/lib/fonts";
import "./globals.css";

export const metadata = {
  title: "Панель ботов",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ru" className={`${plexSans.variable} ${plexMono.variable}`}>
      <body className="flex min-h-screen bg-canvas font-sans text-ink">
        <ToastProvider>
          <Sidebar />
          <main className="min-w-0 flex-1 overflow-x-hidden px-8 py-7">{children}</main>
        </ToastProvider>
      </body>
    </html>
  );
}
```

- [ ] **Step 6: Update the stale comment in `lib/currentUser.ts`**

In `services/admin-web/lib/currentUser.ts`, the comment lists the three
call sites; update the first one from `AppHeader` to `Sidebar`:

```ts
// Третье место, где понадобился этот код (Sidebar, /users, /bots/new) —
```

- [ ] **Step 7: Run the test, then the full suite**

Run: `npx vitest run components/Sidebar.test.tsx`
Expected: PASS (3 tests).

Run: `npm test`
Expected: full existing suite still passes (no other file referenced the
deleted `AppHeader`).

- [ ] **Step 8: Commit**

```bash
git add services/admin-web/components/Sidebar.tsx services/admin-web/components/Sidebar.test.tsx \
  services/admin-web/app/layout.tsx services/admin-web/lib/currentUser.ts
git rm services/admin-web/components/AppHeader.tsx
git commit -m "feat(admin-web): replace AppHeader with a sidebar navigation shell"
```

---

### Task 9: Bot-scoped layout (header + tabs)

**Files:**
- Create: `services/admin-web/app/bots/[id]/layout.tsx`
- Modify: `services/admin-web/app/bots/[id]/page.tsx`
- Test: `services/admin-web/app/bots/[id]/layout.test.tsx`

**Interfaces:**
- Consumes: `fetchBot`, `currentUserIsOwner` (unchanged), `StatusPulse`
  (Task 5), `Tabs`/`TabLink` (Task 6).
- Produces: `BotLayout` — wraps every `/bots/[id]/*` route with a shared
  bot name + phone + `StatusPulse` header and the tab strip (Обзор / Промпты
  / Товары / Настройки / Документы / Чёрный список / Песочница — the last
  only when `currentUserIsOwner()`, same rule the old page used). URLs are
  unchanged. This header is deliberately hand-written rather than built on
  `PageHeader` (Task 4): `PageHeader`'s `action` slot is a single right-aligned
  node for a page-level action button, whereas this header needs the status
  pulse inline next to the title plus a phone line underneath — a shape
  `PageHeader` doesn't cover and shouldn't be stretched to cover speculatively.
  `PageHeader` stays unused until a later screen-group plan (e.g. `/bots`'s
  "+ Новый бот" button) is the intended, simpler consumer.
- `/bots/[id]/page.tsx` becomes the "Обзор" tab's content only: the old
  `<h1>` and the six `<Link>` rows are gone (the layout now renders the
  heading and the tabs) — the page keeps rendering only `<QrPanel>`.

- [ ] **Step 1: Write the failing test**

Create `services/admin-web/app/bots/[id]/layout.test.tsx`:

```tsx
import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import BotLayout from "@/app/bots/[id]/layout";
import { fetchBot, type Bot } from "@/lib/api";
import { currentUserIsOwner } from "@/lib/currentUser";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, fetchBot: vi.fn() };
});
vi.mock("@/lib/currentUser", () => ({
  currentUserIsOwner: vi.fn(),
}));
vi.mock("@/lib/env", () => ({
  API_INTERNAL_URL: "http://api.internal",
}));

const mockedFetchBot = vi.mocked(fetchBot);
const mockedIsOwner = vi.mocked(currentUserIsOwner);

const bot: Bot = {
  id: "1",
  name: "Кофейня «Аромат»",
  enabled: true,
  phone: "996700000000",
  linked_at: "2026-09-01T00:00:00Z",
  system_prompt: "промпт",
  image_prompt: null,
  pdf_prompt: null,
};

it("renders the bot name, connection status and every tab, including the sandbox tab for the owner", async () => {
  mockedFetchBot.mockResolvedValue(bot);
  mockedIsOwner.mockResolvedValue(true);
  const element = await BotLayout({
    params: Promise.resolve({ id: "1" }),
    children: <div>Содержимое вкладки</div>,
  });
  render(element);

  expect(screen.getByText("Кофейня «Аромат»")).toBeInTheDocument();
  expect(screen.getByText("Подключён")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Обзор" })).toHaveAttribute("href", "/bots/1");
  expect(screen.getByRole("link", { name: "Настройки" })).toHaveAttribute("href", "/bots/1/settings");
  expect(screen.getByRole("link", { name: "Песочница" })).toBeInTheDocument();
  expect(screen.getByText("Содержимое вкладки")).toBeInTheDocument();
});

it("hides the sandbox tab for a non-owner", async () => {
  mockedFetchBot.mockResolvedValue(bot);
  mockedIsOwner.mockResolvedValue(false);
  const element = await BotLayout({
    params: Promise.resolve({ id: "1" }),
    children: <div>Содержимое вкладки</div>,
  });
  render(element);
  expect(screen.queryByRole("link", { name: "Песочница" })).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npx vitest run app/bots/\[id\]/layout.test.tsx`
Expected: FAIL — `app/bots/[id]/layout.tsx` doesn't exist yet.

- [ ] **Step 3: Implement `BotLayout`**

Create `services/admin-web/app/bots/[id]/layout.tsx`:

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
  return bot.linked_at ? "connected" : "disconnected";
}

export default async function BotLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const [bot, isOwner] = await Promise.all([fetchBot(API_INTERNAL_URL, id), currentUserIsOwner()]);
  if (!bot) {
    notFound();
  }

  return (
    <div>
      <div className="mb-6">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold text-ink">{bot.name}</h1>
          <StatusPulse status={toConnectionStatus(bot)} />
        </div>
        {bot.phone && <p className="mt-1 font-mono text-sm text-ink-soft">{bot.phone}</p>}
      </div>

      <Tabs>
        <TabLink href={`/bots/${bot.id}`}>Обзор</TabLink>
        <TabLink href={`/bots/${bot.id}/prompts`} exact={false}>
          Промпты
        </TabLink>
        <TabLink href={`/bots/${bot.id}/products`} exact={false}>
          Товары
        </TabLink>
        <TabLink href={`/bots/${bot.id}/settings`} exact={false}>
          Настройки
        </TabLink>
        <TabLink href={`/bots/${bot.id}/documents`} exact={false}>
          Документы
        </TabLink>
        <TabLink href={`/bots/${bot.id}/blocked-numbers`} exact={false}>
          Чёрный список
        </TabLink>
        {isOwner && (
          <TabLink href={`/bots/${bot.id}/sandbox`} exact={false}>
            Песочница
          </TabLink>
        )}
      </Tabs>

      {children}
    </div>
  );
}
```

- [ ] **Step 4: Rewrite `app/bots/[id]/page.tsx` to be the Обзор tab only**

Replace the full content of `services/admin-web/app/bots/[id]/page.tsx`
with:

```tsx
import { QrPanel } from "@/components/QrPanel";
import { fetchBot } from "@/lib/api";
import { API_INTERNAL_URL, API_PROXY_PATH } from "@/lib/env";

export default async function BotOverviewPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const bot = await fetchBot(API_INTERNAL_URL, id);
  if (!bot) {
    // Уже прошли notFound() в layout.tsx (тот же id) — эта ветка практически
    // недостижима, но остаётся на случай гонки между двумя независимыми
    // запросами fetchBot (layout и page получают bota отдельно, Next.js их
    // не передаёт друг другу напрямую).
    return null;
  }
  return <QrPanel initialBot={bot} apiBaseUrl={API_PROXY_PATH} />;
}
```

- [ ] **Step 5: Run the tests, then the full suite**

Run: `npx vitest run app/bots/\[id\]/layout.test.tsx`
Expected: PASS (2 tests).

Run: `npm test`
Expected: full existing suite still passes (`QrPanel.test.tsx` renders
`QrPanel` directly and is unaffected by the page/layout split).

Run: `npm run build`
Expected: build succeeds.

- [ ] **Step 6: Commit**

```bash
git add services/admin-web/app/bots/\[id\]/layout.tsx services/admin-web/app/bots/\[id\]/layout.test.tsx \
  services/admin-web/app/bots/\[id\]/page.tsx
git commit -m "feat(admin-web): add bot-scoped layout with header and tabs"
```

---

## After this plan

This plan's worktree is named for exactly this scope: infrastructure +
navigation shell, nothing else. Once the final whole-branch review is clean,
follow `superpowers:finishing-a-development-branch` to land it, then start a
fresh `writing-plans` pass per remaining spec screen group (bots list,
settings, products, documents/blocked-numbers, prompts, sandbox chrome, the
owner-only platform screens, and finally `/login` + the legacy `@layer base`
cleanup) — each is its own plan, built on the primitives this plan ships.
