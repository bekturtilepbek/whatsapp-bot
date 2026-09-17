# Редизайн кабинета v2 — Волна 1 (фундамент) — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Перевести кабинет `services/admin-web` со визуальной системы
первого редизайна (тёмный сайдбар, `#3459b4`, единый радиус) на систему
«Панель управления» (светлый сайдбар 272px, `#3b5bdb`, двухуровневый
радиус 16px/8-12px, `shadow-card`/`shadow-elevated`, пилюля-статус,
`IconBadge`/`Banner`). Смена токенов и примитивов даёт эффект на всех
экранах автоматически — эта волна не трогает `*Table.tsx`/`*Form.tsx`
consumer-компоненты, только `app/globals.css`, `lib/fonts.ts`,
`components/ui/*`, `components/Sidebar.tsx`, `app/layout.tsx`.

**Spec:** `docs/superpowers/specs/2026-09-18-cabinet-redesign-v2-design.md`

## Global Constraints

- **Ни один `*Table.tsx`/`*Form.tsx` consumer-компонент не меняется в этой
  волне.** Они получают новый вид автоматически через изменённые
  примитивы. Точечные экраны с разметкой в обход примитивов (`QrPanel.tsx`,
  и т.п.) — Волна 2, не эта.
- **Существующие тесты примитивов — регрессионный контракт.** Все
  запросы в них — `getByRole`/`getByText`/`toHaveAttribute`, не по
  классам — смена радиуса/токенов/цвета не должна их сломать. Каждый
  таск подтверждает это прогоном затронутых тестовых файлов, не только
  добавлением новых кейсов.
- **Новые токены только через `@theme` в `globals.css`** — компоненты
  продолжают писать только Tailwind-утилиты (`bg-success-soft`,
  `shadow-elevated`), не хардкодят hex.
- **`--color-sidebar`/`--color-sidebar-ink`/`--color-sidebar-ink-soft`
  удаляются из `@theme`** — единственный потребитель (`Sidebar.tsx`)
  переписывается в этой же волне на светлую палитру (проверено грепом
  перед планированием — больше нигде в `app/`/`components/` не
  используются).
- **`SidebarNavLink` — новый клиентский примитив**, не инлайн-логика
  внутри `Sidebar.tsx` — `Sidebar.tsx` остаётся асинхронным Server
  Component (`fetchCurrentUser()`), `usePathname()` доступен только в
  клиентском поддереве, тот же приём, что уже решает эту же задачу для
  `TabLink`.
- **`animate-ping`, не новый `@keyframes`** — пульс на `StatusPulse`
  использует уже встроенную в Tailwind анимацию (как в v1), не заводит
  собственный keyframe в `globals.css` ради визуально похожего эффекта.
- Conventional Commits; каждый таск коммитит свой рабочий протестированный кусок.

---

### Task 1: Токены, шрифты, сайдбар

**Files:**
- Modify: `services/admin-web/app/globals.css`
- Modify: `services/admin-web/lib/fonts.ts`
- Modify: `services/admin-web/components/Sidebar.tsx`
- Create: `services/admin-web/components/ui/SidebarNavLink.tsx`
- Create: `services/admin-web/components/ui/SidebarNavLink.test.tsx`
- Modify: `services/admin-web/app/layout.tsx`

**Interfaces:**
- `SidebarNavLink` — новый примитив, потребитель — только `Sidebar.tsx` в
  этом таске.

- [ ] **Step 1: Переписать `app/globals.css`**

Replace the full content of `services/admin-web/app/globals.css`:

```css
@import "tailwindcss";

@theme {
  --color-ink: #1d2433;
  --color-ink-soft: #5a6478;
  --color-ink-faint: #8b93a3;
  --color-canvas: #f7f8fb;
  --color-surface: #ffffff;
  --color-surface-alt: #f1f3f8;
  --color-border: #e7eaf0;
  --color-accent: #3b5bdb;
  --color-accent-hover: #2f49c9;
  --color-accent-soft: #edf0fd;
  --color-success: #1c8c4a;
  --color-success-soft: #e6f5ec;
  --color-warning: #b7791f;
  --color-warning-soft: #faf1e2;
  --color-danger: #d12c3c;
  --color-danger-soft: #fdecee;

  --shadow-card: 0 1px 2px rgba(29, 36, 51, 0.04);
  --shadow-elevated: 0 10px 24px -6px rgba(29, 36, 51, 0.08), 0 4px 8px -4px rgba(29, 36, 51, 0.04);

  --font-sans: var(--font-plex-sans), ui-sans-serif, system-ui, sans-serif;
  --font-mono: var(--font-plex-mono), ui-monospace, monospace;
}

/* Редизайн кабинета завершён (ADR-009) — все экраны переведены на
 * components/ui/ примитивы, временный @layer base для немигрированных
 * экранов сослужил свою службу и удалён. Единственное намеренно
 * оставленное правило ниже — не легаси, а постоянный маленький дефолт:
 * браузеры по умолчанию НЕ ставят курсор-руку на <button>. Держим его
 * одним общим правилом вместо того, чтобы дублировать cursor-pointer в
 * каждом месте с голым <button> — например, в Sidebar.tsx ("Выйти") и
 * ToastProvider.tsx (кнопка закрытия), у обоих голая точечная разметка
 * без своего примитива (список неисчерпывающий — не грепать как реестр
 * зависимостей перед правкой правила). :not(:disabled) — иначе disabled-
 * кнопка без своего cursor-utility (как без него был бы SandboxChat.tsx
 * до его собственного патча) получила бы курсор-руку вместо not-allowed. */
@layer base {
  button:not(:disabled) {
    cursor: pointer;
  }
}
```

(Токены `--color-sidebar`/`--color-sidebar-ink`/`--color-sidebar-ink-soft`
из v1 удалены — редизайн v2 делает сайдбар светлым, отдельная палитра ему
больше не нужна. `@layer base` блок с курсором — без изменений, найден
верным в предыдущей волне и никак не связан со сменой цветовой системы.)

- [ ] **Step 2: Добавить вес 700 в `lib/fonts.ts`**

В `services/admin-web/lib/fonts.ts` у `plexSans` расширить `weight`:

```tsx
export const plexSans = IBM_Plex_Sans({
  subsets: ["latin", "cyrillic"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-plex-sans",
  display: "swap",
});
```

(Остальной файл — `plexMono` и комментарий сверху — без изменений.
Новая иерархия типографики v2 использует `font-bold` (700) на заголовках
страниц/панелей — без этого веса в наборе шрифт браузер сам "утолщал" бы
синтетически, что хуже по начертанию, чем реальный файл шрифта.)

- [ ] **Step 3: Создать `components/ui/SidebarNavLink.tsx`**

```tsx
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

interface SidebarNavLinkProps {
  href: string;
  children: ReactNode;
  /** Точное совпадение по умолчанию — как у TabLink. "Боты" в сайдбаре
   * передаёт exact={false}, чтобы оставаться подсвеченным на /bots/new
   * и на любой /bots/[id]/* странице, не только на самом /bots. */
  exact?: boolean;
}

export function SidebarNavLink({ href, children, exact = true }: SidebarNavLinkProps) {
  const pathname = usePathname();
  const isActive = exact ? pathname === href : pathname.startsWith(href);
  return (
    <Link
      href={href}
      aria-current={isActive ? "page" : undefined}
      className={`flex items-center gap-2.5 rounded-lg border-l-[3px] px-2.5 py-2 text-sm transition-colors ${
        isActive
          ? "border-accent bg-accent-soft font-medium text-accent"
          : "border-transparent text-ink-soft hover:bg-surface-alt hover:text-ink"
      }`}
    >
      {children}
    </Link>
  );
}
```

- [ ] **Step 4: Создать `components/ui/SidebarNavLink.test.tsx`**

```tsx
import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { SidebarNavLink } from "@/components/ui/SidebarNavLink";

vi.mock("next/navigation", () => ({
  usePathname: vi.fn(),
}));

import { usePathname } from "next/navigation";
const mockedUsePathname = vi.mocked(usePathname);

it("marks the link active with aria-current on an exact path match", () => {
  mockedUsePathname.mockReturnValue("/dashboard");
  render(<SidebarNavLink href="/dashboard">Дашборд</SidebarNavLink>);
  expect(screen.getByRole("link", { name: "Дашборд" })).toHaveAttribute("aria-current", "page");
});

it("does not mark the link active on a different path", () => {
  mockedUsePathname.mockReturnValue("/users");
  render(<SidebarNavLink href="/dashboard">Дашборд</SidebarNavLink>);
  expect(screen.getByRole("link", { name: "Дашборд" })).not.toHaveAttribute("aria-current");
});

it("matches by prefix when exact is false", () => {
  mockedUsePathname.mockReturnValue("/bots/1/settings");
  render(
    <SidebarNavLink href="/bots" exact={false}>
      Боты
    </SidebarNavLink>,
  );
  expect(screen.getByRole("link", { name: "Боты" })).toHaveAttribute("aria-current", "page");
});
```

- [ ] **Step 5: Переписать `components/Sidebar.tsx`**

Replace the full content of `services/admin-web/components/Sidebar.tsx`:

```tsx
import { logout } from "@/app/login/actions";
import { fetchCurrentUser } from "@/lib/currentUser";
import { SidebarNavLink } from "@/components/ui/SidebarNavLink";

export async function Sidebar() {
  const user = await fetchCurrentUser();
  if (!user) return null;

  return (
    <aside className="sticky top-0 flex h-screen w-[272px] shrink-0 flex-col border-r border-border bg-surface px-3.5 py-5">
      <div className="mb-6 flex items-center gap-2 px-2">
        <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent text-xs font-bold text-white">
          Б
        </span>
        <span className="text-sm font-bold text-ink">Платформа ботов</span>
      </div>

      <nav aria-label="Основная" className="flex flex-col gap-0.5">
        <SidebarNavLink href="/bots" exact={false}>
          Боты
        </SidebarNavLink>
      </nav>

      {user.is_platform_owner && (
        <nav aria-label="Платформа" className="mt-5 flex flex-col gap-0.5">
          <div className="px-2.5 pb-1.5 text-[10.5px] font-bold uppercase tracking-wider text-ink-faint">
            Платформа
          </div>
          <SidebarNavLink href="/dashboard">Дашборд</SidebarNavLink>
          <SidebarNavLink href="/users">Пользователи</SidebarNavLink>
          <SidebarNavLink href="/audit-log">Аудит-лог</SidebarNavLink>
          <SidebarNavLink href="/usage">Расходы</SidebarNavLink>
        </nav>
      )}

      <div className="mt-auto flex items-center gap-2 border-t border-border pt-3.5">
        <span className="min-w-0 flex-1 truncate text-xs text-ink-soft">{user.email}</span>
        <form action={logout}>
          <button type="submit" className="p-0 text-xs text-ink-soft hover:text-ink">
            Выйти
          </button>
        </form>
      </div>
    </aside>
  );
}
```

- [ ] **Step 6: Обновить ширину контентной области в `app/layout.tsx`**

В `services/admin-web/app/layout.tsx` заменить класс контентного `<div>`:

```tsx
          <div className="min-w-0 flex-1 px-10 py-8">{children}</div>
```

(Было `px-8 py-7` — было. Остальной файл, включая комментарий про
`overflow-x-hidden`, без изменений — он не про ширину/отступы, а про
горизонтальный скролл при фокусе, не переоткрывается заново.)

- [ ] **Step 7: Прогнать существующие тесты `Sidebar.test.tsx` и убедиться, что они проходят без изменений**

Run: `npx vitest run components/Sidebar.test.tsx components/ui/SidebarNavLink.test.tsx`
Expected: `Sidebar.test.tsx` — все 3 существующих кейса проходят без
единой правки файла (запросы по `getByRole("link", ...)`/`getByText`, не
по классам); `SidebarNavLink.test.tsx` — новые 3 кейса проходят.

- [ ] **Step 8: Прогнать полный набор, typecheck и билд**

Run: `npm test`
Expected: полный набор проходит (правки токенов/радиуса не ломают
существующие тесты других примитивов — они не по классам).

Run: `npx tsc --noEmit`
Expected: чисто.

Run: `npm run build`
Expected: билд проходит.

- [ ] **Step 9: Commit**

```bash
git add services/admin-web/app/globals.css services/admin-web/lib/fonts.ts \
  services/admin-web/components/Sidebar.tsx services/admin-web/components/ui/SidebarNavLink.tsx \
  services/admin-web/components/ui/SidebarNavLink.test.tsx services/admin-web/app/layout.tsx
git commit -m "feat(admin-web): v2 design tokens, fonts and light sidebar"
```

---

### Task 2: Радиус/анимация на кнопках и полях ввода

**Files:**
- Modify: `services/admin-web/components/ui/Button.tsx`
- Modify: `services/admin-web/components/ui/Input.tsx`
- Modify: `services/admin-web/components/ui/Textarea.tsx`
- Modify: `services/admin-web/components/ui/Select.tsx`

**Interfaces:** нет новых — только классы существующих примитивов.
`NumberField.tsx` оборачивает `Input` и своих классов не имеет — не
трогается, наследует изменение автоматически. `Switch.tsx` уже
`rounded-full` и ссылается только на токены (`bg-border`/`checked:bg-accent`)
— не трогается вообще, подтягивает новые цвета из `@theme` без правки
файла.

- [ ] **Step 1: `Button.tsx` — радиус и микро-отклик на клик**

В `services/admin-web/components/ui/Button.tsx` заменить `BUTTON_BASE_CLASSES`:

```tsx
const BUTTON_BASE_CLASSES =
  "inline-flex items-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium leading-tight transition-colors active:scale-[.97] disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2";
```

(Было `rounded-md`, без `active:scale-[.97]`. Остальной файл —
`BUTTON_VARIANT_CLASSES`, `buttonClasses`, `Button` — без изменений;
значения `bg-accent`/`hover:bg-accent-hover`/`text-danger` и т.п. уже
подтягивают новые hex из `@theme` без правки.)

- [ ] **Step 2: `Input.tsx` — радиус**

В `services/admin-web/components/ui/Input.tsx` в className заменить
`rounded-md` на `rounded-lg`.

- [ ] **Step 3: `Textarea.tsx` — радиус**

В `services/admin-web/components/ui/Textarea.tsx` в className заменить
`rounded-md` на `rounded-lg`.

- [ ] **Step 4: `Select.tsx` — радиус**

В `services/admin-web/components/ui/Select.tsx` в className заменить
`rounded-md` на `rounded-lg`.

- [ ] **Step 5: Прогнать существующие тесты и типы**

Run: `npx vitest run components/ui/Button.test.tsx components/ui/Input.test.tsx components/ui/Textarea.test.tsx components/ui/Select.test.tsx components/ui/NumberField.test.tsx components/ui/Switch.test.tsx`
Expected: все проходят без единой правки тестовых файлов (запросы по
`getByRole`/`getByPlaceholderText`/`getByDisplayValue`, не по классам).

Run: `npm run build`
Expected: билд проходит.

- [ ] **Step 6: Commit**

```bash
git add services/admin-web/components/ui/Button.tsx services/admin-web/components/ui/Input.tsx \
  services/admin-web/components/ui/Textarea.tsx services/admin-web/components/ui/Select.tsx
git commit -m "feat(admin-web): v2 radius and click feedback on form controls"
```

---

### Task 3: Радиус и тень на поверхностях (Card/Table/EmptyState)

**Files:**
- Modify: `services/admin-web/components/ui/Card.tsx`
- Modify: `services/admin-web/components/ui/Table.tsx`
- Modify: `services/admin-web/components/ui/EmptyState.tsx`

- [ ] **Step 1: `Card.tsx` — радиус 16px + тень**

Replace the full content of `services/admin-web/components/ui/Card.tsx`:

```tsx
import type { HTMLAttributes } from "react";

type CardProps = HTMLAttributes<HTMLDivElement>;

export function Card({ className = "", ...props }: CardProps) {
  return (
    <div className={`rounded-2xl border border-border bg-surface shadow-card ${className}`} {...props} />
  );
}
```

- [ ] **Step 2: `Table.tsx` — тот же радиус/тень на обёртке**

Replace the full content of `services/admin-web/components/ui/Table.tsx`:

```tsx
import type { ReactNode } from "react";

interface TableProps {
  children: ReactNode;
}

const WRAPPER_CLASSES = [
  "overflow-x-auto rounded-2xl border border-border bg-surface shadow-card",
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

- [ ] **Step 3: `EmptyState.tsx` — радиус 16px (без тени — пунктирная рамка, а не приподнятая поверхность)**

В `services/admin-web/components/ui/EmptyState.tsx` в className корневого
`<div>` заменить `rounded-lg` на `rounded-2xl`.

- [ ] **Step 4: Прогнать существующие тесты**

Run: `npx vitest run components/ui/Card.test.tsx components/ui/Table.test.tsx components/ui/EmptyState.test.tsx`
Expected: все проходят без правки тестовых файлов.

Run: `npm run build`
Expected: билд проходит.

- [ ] **Step 5: Commit**

```bash
git add services/admin-web/components/ui/Card.tsx services/admin-web/components/ui/Table.tsx \
  services/admin-web/components/ui/EmptyState.tsx
git commit -m "feat(admin-web): v2 radius and elevation on surfaces"
```

---

### Task 4: `Badge` — новые soft-токены; `StatusPulse` — пилюля

**Files:**
- Modify: `services/admin-web/components/ui/Badge.tsx`
- Modify: `services/admin-web/components/ui/StatusPulse.tsx`

- [ ] **Step 1: `Badge.tsx` — заменить `paused` на настоящий soft-токен**

В `services/admin-web/components/ui/Badge.tsx` в `BADGE_VARIANT_CLASSES`
заменить строку `paused`:

```tsx
  paused: "bg-warning-soft text-warning",
```

(Было `bg-warning/15 text-warning` — приближение через прозрачность,
теперь есть настоящий `--color-warning-soft` токен в `@theme`, используем
его. `owner`/`neutral` без изменений — уже ссылались на существующие
soft-токены правильно.)

- [ ] **Step 2: Переписать `StatusPulse.tsx` на пилюлю**

Replace the full content of `services/admin-web/components/ui/StatusPulse.tsx`:

```tsx
export type BotConnectionStatus = "connected" | "pending" | "disconnected";

interface StatusPulseProps {
  status: BotConnectionStatus;
}

interface StatusConfig {
  label: string;
  pillClass: string;
  dotClass: string;
  animated: boolean;
}

const STATUS_CONFIG: Record<BotConnectionStatus, StatusConfig> = {
  connected: {
    label: "Подключён",
    pillClass: "bg-success-soft text-success",
    dotClass: "bg-success",
    animated: true,
  },
  pending: {
    label: "Подключается",
    pillClass: "bg-warning-soft text-warning",
    dotClass: "bg-warning",
    animated: false,
  },
  disconnected: {
    label: "Не подключён",
    pillClass: "bg-surface-alt text-ink-soft",
    dotClass: "bg-ink-faint",
    animated: false,
  },
};

export function StatusPulse({ status }: StatusPulseProps) {
  const config = STATUS_CONFIG[status];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${config.pillClass}`}
    >
      <span className="relative inline-flex h-1.5 w-1.5 rounded-full">
        {config.animated && (
          <span
            className={`absolute inset-0 rounded-full opacity-75 motion-reduce:hidden ${config.dotClass} animate-ping`}
          />
        )}
        <span className={`relative inline-flex h-1.5 w-1.5 rounded-full ${config.dotClass}`} />
      </span>
      {config.label}
    </span>
  );
}
```

(Публичный API (`status` проп, три значения) не меняется — потребители
`BotsTable.tsx`/`DashboardTable.tsx`/`app/bots/[id]/layout.tsx` не
трогаются в этой волне. Пульс — тот же `animate-ping`, что был в v1, только
у `connected`, ровно как раньше; изменилась ТОЛЬКО внешняя обёртка точки
и подписи в единую пилюлю с мягким фоном вместо плоского текста рядом с
точкой.)

- [ ] **Step 3: Прогнать существующие тесты**

Run: `npx vitest run components/ui/Badge.test.tsx components/ui/StatusPulse.test.tsx`
Expected: оба файла проходят без правки — `Badge.test.tsx` по тексту
внутри бейджа, `StatusPulse.test.tsx` по русской подписи, не по классам.

- [ ] **Step 4: Прогнать полный набор — проверить экраны, использующие `StatusPulse`, не сломались по факту (не по коду, они не трогаются)**

Run: `npm test`
Expected: `BotsTable.test.tsx`, `DashboardTable.test.tsx`,
`app/bots/[id]/layout.test.tsx` — все проходят без изменений (они
рендерят `<StatusPulse status={...}/>` и проверяют по русской подписи,
не по внутренней разметке).

Run: `npm run build`
Expected: билд проходит.

- [ ] **Step 5: Commit**

```bash
git add services/admin-web/components/ui/Badge.tsx services/admin-web/components/ui/StatusPulse.tsx
git commit -m "feat(admin-web): v2 pill-shaped status pulse and badge soft tokens"
```

---

### Task 5: `PageHeader` eyebrow; новые примитивы `IconBadge`, `Banner`

**Files:**
- Modify: `services/admin-web/components/ui/PageHeader.tsx`
- Modify: `services/admin-web/components/ui/PageHeader.test.tsx` (append one test only)
- Create: `services/admin-web/components/ui/IconBadge.tsx`
- Create: `services/admin-web/components/ui/IconBadge.test.tsx`
- Create: `services/admin-web/components/ui/Banner.tsx`
- Create: `services/admin-web/components/ui/Banner.test.tsx`

**Interfaces:**
- `IconBadge`/`Banner` — новые примитивы без сегодняшних потребителей в
  коде (первый потребитель — `QrPanel.tsx` в Волне 2). Наличие только
  примитива+теста в этой волне — намеренно: сама библиотека компонентов
  готова, точечное подключение — отдельный таск с собственным ревью.

- [ ] **Step 1: Добавить `eyebrow` в `PageHeader.tsx`, поднять вес заголовка**

Replace the full content of `services/admin-web/components/ui/PageHeader.tsx`:

```tsx
import type { ReactNode } from "react";

interface PageHeaderProps {
  title: string;
  eyebrow?: string;
  subtitle?: string;
  action?: ReactNode;
}

export function PageHeader({ title, eyebrow, subtitle, action }: PageHeaderProps) {
  return (
    <div className="mb-6 flex items-start justify-between gap-4">
      <div>
        {eyebrow && (
          <div className="mb-1.5 text-xs font-bold uppercase tracking-wider text-ink-soft">{eyebrow}</div>
        )}
        <h1 className="text-2xl font-bold tracking-tight text-ink">{title}</h1>
        {subtitle && <p className="mt-1.5 text-sm leading-relaxed text-ink-soft">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}
```

- [ ] **Step 2: Добавить один новый тест в `PageHeader.test.tsx`**

Append to the end of `services/admin-web/components/ui/PageHeader.test.tsx`:

```tsx
it("renders an optional eyebrow above the title", () => {
  render(<PageHeader title="Боты" eyebrow="Платформа" />);
  expect(screen.getByText("Платформа")).toBeInTheDocument();
});
```

- [ ] **Step 3: Прогнать `PageHeader.test.tsx` — 4 кейса (3 старых + 1 новый)**

Run: `npx vitest run components/ui/PageHeader.test.tsx`
Expected: PASS, 4 теста — 3 старых без изменений + новый про eyebrow.

- [ ] **Step 4: Создать `components/ui/IconBadge.tsx`**

```tsx
import type { ReactNode } from "react";

type IconBadgeVariant = "success" | "accent" | "warning" | "danger";
type IconBadgeSize = "md" | "lg";

interface IconBadgeProps {
  variant?: IconBadgeVariant;
  size?: IconBadgeSize;
  children: ReactNode;
}

const VARIANT_CLASSES: Record<IconBadgeVariant, string> = {
  success: "bg-success-soft text-success",
  accent: "bg-accent-soft text-accent",
  warning: "bg-warning-soft text-warning",
  danger: "bg-danger-soft text-danger",
};

const SIZE_CLASSES: Record<IconBadgeSize, string> = {
  md: "h-11 w-11 [&_svg]:h-5 [&_svg]:w-5",
  lg: "h-[60px] w-[60px] [&_svg]:h-7 [&_svg]:w-7",
};

export function IconBadge({ variant = "accent", size = "md", children }: IconBadgeProps) {
  return (
    <span
      className={`inline-flex flex-none items-center justify-center rounded-full ${VARIANT_CLASSES[variant]} ${SIZE_CLASSES[size]}`}
    >
      {children}
    </span>
  );
}
```

- [ ] **Step 5: Создать `components/ui/IconBadge.test.tsx`**

```tsx
import { expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { IconBadge } from "@/components/ui/IconBadge";

it("renders its icon child", () => {
  render(
    <IconBadge variant="success">
      <svg role="img" aria-label="Готово" />
    </IconBadge>,
  );
  expect(screen.getByRole("img", { name: "Готово" })).toBeInTheDocument();
});

it("renders every variant without crashing", () => {
  const { rerender } = render(<IconBadge variant="success">x</IconBadge>);
  expect(screen.getByText("x")).toBeInTheDocument();
  rerender(<IconBadge variant="accent">x</IconBadge>);
  expect(screen.getByText("x")).toBeInTheDocument();
  rerender(<IconBadge variant="warning">x</IconBadge>);
  expect(screen.getByText("x")).toBeInTheDocument();
  rerender(<IconBadge variant="danger">x</IconBadge>);
  expect(screen.getByText("x")).toBeInTheDocument();
});
```

- [ ] **Step 6: Создать `components/ui/Banner.tsx`**

```tsx
import type { ReactNode } from "react";

type BannerVariant = "success" | "accent" | "warning" | "danger";

interface BannerProps {
  variant?: BannerVariant;
  icon: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
}

const SURFACE_CLASSES: Record<BannerVariant, string> = {
  success: "bg-success-soft border-success/25",
  accent: "bg-accent-soft border-accent/25",
  warning: "bg-warning-soft border-warning/25",
  danger: "bg-danger-soft border-danger/25",
};

const TITLE_CLASSES: Record<BannerVariant, string> = {
  success: "text-success",
  accent: "text-accent",
  warning: "text-warning",
  danger: "text-danger",
};

export function Banner({ variant = "accent", icon, title, description, action }: BannerProps) {
  return (
    <div
      className={`mb-5 flex flex-wrap items-start justify-between gap-4 rounded-xl border p-4 shadow-elevated ${SURFACE_CLASSES[variant]}`}
    >
      <div className="flex items-start gap-3">
        <span className={`mt-0.5 flex-none ${TITLE_CLASSES[variant]}`}>{icon}</span>
        <div>
          <p className={`text-sm font-bold ${TITLE_CLASSES[variant]}`}>{title}</p>
          {description && <p className="mt-0.5 text-[13px] leading-relaxed text-ink-soft">{description}</p>}
        </div>
      </div>
      {action}
    </div>
  );
}
```

- [ ] **Step 7: Создать `components/ui/Banner.test.tsx`**

```tsx
import { expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Banner } from "@/components/ui/Banner";

it("renders the title, optional description and action", () => {
  render(
    <Banner
      icon={<svg aria-hidden="true" />}
      title="Бот активен — отвечает на сообщения"
      description="Входящие запросы обрабатываются автоматически"
      action={<button>Пауза</button>}
    />,
  );
  expect(screen.getByText("Бот активен — отвечает на сообщения")).toBeInTheDocument();
  expect(screen.getByText("Входящие запросы обрабатываются автоматически")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Пауза" })).toBeInTheDocument();
});

it("omits the description when not given", () => {
  render(<Banner icon={<svg aria-hidden="true" />} title="Бот на паузе" />);
  expect(screen.getByText("Бот на паузе")).toBeInTheDocument();
});

it("renders every variant without crashing", () => {
  const { rerender } = render(<Banner icon={<svg aria-hidden="true" />} title="x" variant="success" />);
  expect(screen.getByText("x")).toBeInTheDocument();
  rerender(<Banner icon={<svg aria-hidden="true" />} title="x" variant="accent" />);
  expect(screen.getByText("x")).toBeInTheDocument();
  rerender(<Banner icon={<svg aria-hidden="true" />} title="x" variant="warning" />);
  expect(screen.getByText("x")).toBeInTheDocument();
  rerender(<Banner icon={<svg aria-hidden="true" />} title="x" variant="danger" />);
  expect(screen.getByText("x")).toBeInTheDocument();
});
```

- [ ] **Step 8: Прогнать полный набор, typecheck и билд**

Run: `npm test`
Expected: полный набор проходит, включая новые `IconBadge.test.tsx`/
`Banner.test.tsx` и обновлённый `PageHeader.test.tsx` (4 теста).

Run: `npx tsc --noEmit`
Expected: чисто.

Run: `npm run build`
Expected: билд проходит.

- [ ] **Step 9: Commit**

```bash
git add services/admin-web/components/ui/PageHeader.tsx services/admin-web/components/ui/PageHeader.test.tsx \
  services/admin-web/components/ui/IconBadge.tsx services/admin-web/components/ui/IconBadge.test.tsx \
  services/admin-web/components/ui/Banner.tsx services/admin-web/components/ui/Banner.test.tsx
git commit -m "feat(admin-web): v2 page header eyebrow and IconBadge/Banner primitives"
```

---

## After this plan

Волна 2 (не в этом плане): точечные правки экранов, у которых есть
разметка в обход примитивов — как минимум `QrPanel.tsx` (переезд на
`IconBadge` для подключённого состояния + `Banner`+`Switch` на
`bot.enabled` — эндпоинт уже есть, `PATCH /bots/{id}`, нужен только
`patchBotEnabled()` в `lib/api.ts` по образцу `patchBotName`) и сверка
`DashboardTable.tsx`/`app/bots/[id]/layout.tsx`/`app/login/page.tsx`
живым прогоном. Затем — финальная живая проверка всего кабинета на
docker compose разом (не по экрану, объём небольшой). Не начинать без
подтверждения — эта волна и так уже начата по прямому запросу
пользователя «переделаем весь проект», подтверждение получено на уровне
всей инициативы.
