# Редизайн кабинета v2 — Волна 2 (точечные правки) — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Волна 1 перевела `components/ui/*`/`Sidebar.tsx`/`globals.css` на
систему v2 — большинство экранов переоделись автоматически. Эта волна
закрывает точки, где есть разметка В ОБХОД примитивов (список составлен
по факту финального ревью Волны 1 и собственному разделу спеки «Экраны —
где нужны точечные правки»), плюс доводит до конца два пункта, отложенные
из Волны 1 намеренно (`className` на `Banner`/`IconBadge` — пока не было
реального потребителя; несогласованный логотип на `/login`).

**Spec:** `docs/superpowers/specs/2026-09-18-cabinet-redesign-v2-design.md`
**Предыдущая волна:** `docs/superpowers/plans/2026-09-18-cabinet-v2-foundation.md`
(смёржена в `dev`, коммиты `73a4eb4..2137a6f`)

## Global Constraints

- Каждый таск — самостоятельный точечный фикс на разных файлах; порядок
  между тасками 1-4 не важен (независимы), таск 5 (`QrPanel`) может идти
  в любой момент — он не зависит от `className`-фикса (Banner/IconBadge
  используются в нём без кастомного className, `mb-5`/размеры по
  умолчанию достаточны).
- **Никаких новых бизнес-полей.** `bot.enabled` уже существует
  (`lib/api.ts::Bot.enabled`), `PATCH /bots/{id}` уже принимает `enabled`
  на бэкенде (`services/api/src/api/schemas/bots.py::BotPatch`,
  `services/api/src/api/routers/bots.py`) — эта волна добавляет только
  фронтенд-функцию `patchBotEnabled`, зеркалящую `patchBotName` 1:1.
  Бэкенд не трогается.
- Радиус для мелких элементов (миниатюры фото, file-input кнопки, код-блоки)
  — `rounded-lg`, не `rounded-2xl` (это не карточки/панели, а мелкая
  инлайн-разметка — двухуровневая система спеки, см. её раздел
  «Радиус — двухуровневый»).
- Существующие тесты, которые не упомянуты явно как изменяемые в таске,
  должны продолжать проходить без правок (запросы по role/text, не по
  классам — тот же регрессионный контракт, что в Волне 1).
- Conventional Commits; каждый таск коммитит свой рабочий протестированный кусок.

---

### Task 1: `className` на `Banner`/`IconBadge`

**Files:**
- Modify: `services/admin-web/components/ui/Banner.tsx`
- Modify: `services/admin-web/components/ui/Banner.test.tsx`
- Modify: `services/admin-web/components/ui/IconBadge.tsx`
- Modify: `services/admin-web/components/ui/IconBadge.test.tsx`

- [ ] **Step 1: Добавить `className` в `Banner.tsx`**

Replace the full content of `services/admin-web/components/ui/Banner.tsx`:

```tsx
import type { ReactNode } from "react";

type BannerVariant = "success" | "accent" | "warning" | "danger";

interface BannerProps {
  variant?: BannerVariant;
  icon: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
  className?: string;
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

export function Banner({
  variant = "accent",
  icon,
  title,
  description,
  action,
  className = "",
}: BannerProps) {
  return (
    <div
      className={`mb-5 flex flex-wrap items-start justify-between gap-4 rounded-xl border p-4 shadow-elevated ${SURFACE_CLASSES[variant]} ${className}`}
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

(Только добавлен `className?: string` в проп и в конец строки классов —
`mb-5`/остальная разметка не менялись, как у `Card.tsx`, которая
форвардит `className` тем же приёмом.)

- [ ] **Step 2: Добавить тест на `className` в `Banner.test.tsx`**

Append to the end of `services/admin-web/components/ui/Banner.test.tsx`:

```tsx
it("merges a caller className with its own", () => {
  const { container } = render(
    <Banner icon={<svg aria-hidden="true" />} title="X" className="custom-class" />,
  );
  expect(container.firstChild).toHaveClass("custom-class");
});
```

(Использует `container.firstChild` — Banner рендерит один корневой `<div>`,
поэтому это надёжнее, чем подниматься по DOM от текста заголовка через
несколько уровней вложенности, где легко промахнуться мимо корневого узла.)

- [ ] **Step 3: Добавить `className` в `IconBadge.tsx`**

Replace the full content of `services/admin-web/components/ui/IconBadge.tsx`:

```tsx
import type { ReactNode } from "react";

type IconBadgeVariant = "success" | "accent" | "warning" | "danger";
type IconBadgeSize = "md" | "lg";

interface IconBadgeProps {
  variant?: IconBadgeVariant;
  size?: IconBadgeSize;
  children: ReactNode;
  className?: string;
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

export function IconBadge({ variant = "accent", size = "md", children, className = "" }: IconBadgeProps) {
  return (
    <span
      className={`inline-flex flex-none items-center justify-center rounded-full ${VARIANT_CLASSES[variant]} ${SIZE_CLASSES[size]} ${className}`}
    >
      {children}
    </span>
  );
}
```

- [ ] **Step 4: Добавить тест на `className` в `IconBadge.test.tsx`**

Append to the end of `services/admin-web/components/ui/IconBadge.test.tsx`:

```tsx
it("merges a caller className with its own", () => {
  render(
    <IconBadge className="custom-class">
      <svg role="img" aria-label="X" />
    </IconBadge>,
  );
  expect(screen.getByRole("img", { name: "X" }).parentElement).toHaveClass("custom-class");
});
```

- [ ] **Step 5: Прогнать тесты, typecheck, билд**

Run: `npx vitest run components/ui/Banner.test.tsx components/ui/IconBadge.test.tsx`
Expected: PASS — исходные тесты без изменений + один новый на файл.

Run (from `services/admin-web/`): `npm test && npx tsc --noEmit && npm run build`
Expected: всё чисто.

- [ ] **Step 6: Commit**

```bash
git add services/admin-web/components/ui/Banner.tsx services/admin-web/components/ui/Banner.test.tsx \
  services/admin-web/components/ui/IconBadge.tsx services/admin-web/components/ui/IconBadge.test.tsx
git commit -m "feat(admin-web): forward className on Banner and IconBadge"
```

---

### Task 2: Новый примитив `BrandMark`; применить в `Sidebar.tsx` и `/login`

**Files:**
- Create: `services/admin-web/components/ui/BrandMark.tsx`
- Create: `services/admin-web/components/ui/BrandMark.test.tsx`
- Modify: `services/admin-web/components/Sidebar.tsx`
- Modify: `services/admin-web/app/login/page.tsx`

**Contexts:** финальное ревью Волны 1 нашло расхождение — `Sidebar.tsx`
переехал на новый лого-лок-ап (`h-7 w-7 rounded-lg`/`font-bold`) в Task 1
той волны, а `/login` остался на старом (`h-6 w-6 rounded-md`/
`font-semibold`) — единственный экран, где логотип виден рядом с новой
системой. Извлекается общий примитив вместо копипаста разметки во второй
раз.

- [ ] **Step 1: Создать `components/ui/BrandMark.tsx`**

```tsx
export function BrandMark() {
  return (
    <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent text-xs font-bold text-white">
      Б
    </span>
  );
}
```

(Буква и стили — точная копия текущей разметки `Sidebar.tsx`, единственного
уже верного места. `/login` подтягивается к нему, не наоборот.)

- [ ] **Step 2: Создать `components/ui/BrandMark.test.tsx`**

```tsx
import { expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { BrandMark } from "@/components/ui/BrandMark";

it("renders the platform initial", () => {
  render(<BrandMark />);
  expect(screen.getByText("Б")).toBeInTheDocument();
});
```

- [ ] **Step 3: Использовать `BrandMark` в `Sidebar.tsx`**

В `services/admin-web/components/Sidebar.tsx` добавить импорт и заменить
инлайн-разметку логотипа:

```tsx
import { logout } from "@/app/login/actions";
import { fetchCurrentUser } from "@/lib/currentUser";
import { BrandMark } from "@/components/ui/BrandMark";
import { SidebarNavLink } from "@/components/ui/SidebarNavLink";

export async function Sidebar() {
  const user = await fetchCurrentUser();
  if (!user) return null;

  return (
    <aside className="sticky top-0 flex h-screen w-[272px] shrink-0 flex-col border-r border-border bg-surface px-3.5 py-5">
      <div className="mb-6 flex items-center gap-2 px-2">
        <BrandMark />
        <span className="text-sm font-bold text-ink">Платформа ботов</span>
      </div>
```

(Остальной файл — `nav`-блоки, `SidebarNavLink`, футер с логаутом — без
изменений, только замена `<span className="flex h-7 w-7 ...">Б</span>` на
`<BrandMark />` и новый импорт.)

- [ ] **Step 4: Использовать `BrandMark` в `app/login/page.tsx`**

В `services/admin-web/app/login/page.tsx` добавить импорт и заменить
инлайн-разметку логотипа:

```tsx
"use client";

import { useActionState, useEffect, useRef } from "react";
import { login } from "./actions";
import { useToast } from "@/components/ToastProvider";
import { BrandMark } from "@/components/ui/BrandMark";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";

export default function LoginPage() {
  const { showError } = useToast();
  const [error, formAction, pending] = useActionState(login, null);
  const wasPending = useRef(false);

  useEffect(() => {
    if (wasPending.current && !pending && error) {
      showError(error);
    }
    wasPending.current = pending;
  }, [pending, error, showError]);

  return (
    <main className="flex min-h-full items-center justify-center">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center justify-center gap-2">
          <BrandMark />
          <span className="text-sm font-bold text-ink">Платформа ботов</span>
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

(Изменения: новый импорт `BrandMark`, замена инлайн `<span>` на
`<BrandMark />`, подпись рядом с ним `font-semibold`→`font-bold` для
согласованности с сайдбаром — единственная текстовая деталь, которую
`BrandMark` сам не покрывает, так как несёт только сам значок. Заголовок
формы `«Вход»` и всё остальное — без изменений.)

- [ ] **Step 5: Прогнать существующие тесты**

Run: `npx vitest run components/ui/BrandMark.test.tsx components/Sidebar.test.tsx app/login/page.test.tsx`
Expected: PASS — `Sidebar.test.tsx`/`page.test.tsx` не проверяют классы
логотипа (только текст/роли), проходят без правок; новый
`BrandMark.test.tsx` — 1 тест.

Run (from `services/admin-web/`): `npm test && npx tsc --noEmit && npm run build`
Expected: всё чисто.

- [ ] **Step 6: Commit**

```bash
git add services/admin-web/components/ui/BrandMark.tsx services/admin-web/components/ui/BrandMark.test.tsx \
  services/admin-web/components/Sidebar.tsx services/admin-web/app/login/page.tsx
git commit -m "feat(admin-web): extract BrandMark primitive, fix login/sidebar logo mismatch"
```

---

### Task 3: `ToastProvider.tsx` — тень v2

**Files:**
- Modify: `services/admin-web/components/ToastProvider.tsx`

- [ ] **Step 1: Заменить `shadow-md` на `shadow-elevated`**

В `services/admin-web/components/ToastProvider.tsx` в className тоста
заменить `shadow-md` на `shadow-elevated`:

```tsx
            className={`flex max-w-[24rem] items-center gap-3 rounded-lg border-l-[3px] bg-surface px-4 py-3 text-sm text-ink shadow-elevated ${
              toast.kind === "error" ? "border-l-danger" : "border-l-success"
            }`}
```

(Единственное изменение — токен тени; `rounded-lg`/остальная разметка
уже соответствуют v2, менять не нужно.)

- [ ] **Step 2: Прогнать тесты**

Run: `npx vitest run components/ToastProvider.test.tsx`
Expected: PASS без изменений (тест не проверяет тень).

Run (from `services/admin-web/`): `npm test && npm run build`
Expected: чисто.

- [ ] **Step 3: Commit**

```bash
git add services/admin-web/components/ToastProvider.tsx
git commit -m "feat(admin-web): use v2 elevated shadow on toasts"
```

---

### Task 4: Сузить оставшиеся `rounded-md` до `rounded-lg` в обходной разметке

**Files:**
- Modify: `services/admin-web/components/AuditLogTable.tsx`
- Modify: `services/admin-web/components/DocumentsTable.tsx`
- Modify: `services/admin-web/components/ProductForm.tsx`
- Modify: `services/admin-web/components/ProductsTable.tsx`

**Context:** это точки, где компоненты рисуют мелкую разметку САМИ, в
обход примитивов `components/ui/` (миниатюры фото, file-input кнопки,
JSON-код-блок) — единственные оставшиеся `rounded-md` в проекте вне
`/login` (Task 2) и `QrPanel.tsx` (Task 5), см. финальное ревью Волны 1.

- [ ] **Step 1: `AuditLogTable.tsx` — код-блок**

В `services/admin-web/components/AuditLogTable.tsx` строка ~121 заменить
`rounded-md` на `rounded-lg`:

```tsx
                          <pre className="mt-1.5 max-w-md overflow-x-auto rounded-lg bg-surface-alt p-2 text-xs">
```

- [ ] **Step 2: `DocumentsTable.tsx` — кнопка file-input**

В `services/admin-web/components/DocumentsTable.tsx` строка ~62 заменить
`file:rounded-md` на `file:rounded-lg`:

```tsx
            className="mt-1.5 block text-sm text-ink-soft file:mr-3 file:rounded-lg file:border file:border-border file:bg-surface file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-ink hover:file:border-ink-faint disabled:opacity-60"
```

- [ ] **Step 3: `ProductForm.tsx` — три места (две кнопки file-input + миниатюра фото)**

В `services/admin-web/components/ProductForm.tsx`:

Строка ~249 (input без `product`, без `disabled` в className):
```tsx
              className="mt-1.5 block text-sm text-ink-soft file:mr-3 file:rounded-lg file:border file:border-border file:bg-surface file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-ink hover:file:border-ink-faint"
```

Строка ~264 (миниатюра фото):
```tsx
                  className="h-24 w-24 rounded-lg object-cover"
```

Строка ~287 (input с `disabled:opacity-60` в className):
```tsx
              className="mt-1.5 block text-sm text-ink-soft file:mr-3 file:rounded-lg file:border file:border-border file:bg-surface file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-ink hover:file:border-ink-faint disabled:opacity-60"
```

(Все три — только `rounded-md`→`rounded-lg` внутри уже существующей
строки классов, остальной JSX не меняется.)

- [ ] **Step 4: `ProductsTable.tsx` — миниатюра фото**

В `services/admin-web/components/ProductsTable.tsx` строка ~99 заменить
`rounded-md` на `rounded-lg`:

```tsx
                      className="h-12 w-12 rounded-lg object-cover"
```

- [ ] **Step 5: Подтвердить, что `rounded-md` не осталось нигде вне `node_modules`/`.next`**

Run: `grep -rn "rounded-md" services/admin-web --include="*.tsx" | grep -v node_modules | grep -v .next`
Expected: пусто (если что-то осталось — либо забытое место из этого
таска, либо `QrPanel.tsx`/`login/page.tsx`, которые закрывают Task 2 и
Task 5 этой же волны — свериться, что они тоже закрыты к концу волны).

- [ ] **Step 6: Прогнать тесты**

Run: `npx vitest run components/AuditLogTable.test.tsx components/DocumentsTable.test.tsx components/ProductForm.test.tsx components/ProductsTable.test.tsx`
Expected: PASS без изменений (тесты не проверяют классы).

Run (from `services/admin-web/`): `npm test && npm run build`
Expected: чисто.

- [ ] **Step 7: Commit**

```bash
git add services/admin-web/components/AuditLogTable.tsx services/admin-web/components/DocumentsTable.tsx \
  services/admin-web/components/ProductForm.tsx services/admin-web/components/ProductsTable.tsx
git commit -m "feat(admin-web): bump remaining inline radius to v2 scale"
```

---

### Task 5: `QrPanel.tsx` — `IconBadge`-герой + `Banner`/`Switch` на `bot.enabled`

**Files:**
- Modify: `services/admin-web/lib/api.ts`
- Modify: `services/admin-web/components/QrPanel.tsx`
- Modify: `services/admin-web/components/QrPanel.test.tsx`

**Context:** единственный реальный сегодняшний потребитель `IconBadge`/
`Banner`, заложенных в Волне 1. `bot.enabled` — существующее поле
(FEATURES.md 1.7, «пауза бота»), сейчас переключается только из списка
ботов бейджем — здесь появляется первый способ переключить его прямо со
страницы бота. `PATCH /bots/{id}` уже принимает `enabled` на бэкенде —
backend-работы не требуется, только новая фронтенд-функция.

- [ ] **Step 1: Добавить `patchBotEnabled` в `lib/api.ts`**

В `services/admin-web/lib/api.ts` добавить после `patchBotName`:

```tsx
/** FEATURES.md 1.7 — пауза бота. Тот же паттерн, что patchBotName — PATCH
 * с одним полем, бэкенд уже принимает `enabled` (BotPatch). */
export async function patchBotEnabled(baseUrl: string, id: string, enabled: boolean): Promise<Bot> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await apiFetch(`${base}/bots/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
  if (!res.ok) {
    throw new Error(`PATCH /bots/${id} failed: ${res.status}`);
  }
  return (await res.json()) as Bot;
}
```

- [ ] **Step 2: Переписать `QrPanel.tsx`**

Replace the full content of `services/admin-web/components/QrPanel.tsx`:

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchBot, logoutBot, patchBotEnabled, qrImageUrl, type Bot } from "@/lib/api";
import { useToast } from "@/components/ToastProvider";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { IconBadge } from "@/components/ui/IconBadge";
import { Switch } from "@/components/ui/Switch";

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
  const [togglingEnabled, setTogglingEnabled] = useState(false);
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

  const handleToggleEnabled = async () => {
    const next = !bot.enabled;
    setTogglingEnabled(true);
    try {
      const updated = await patchBotEnabled(apiBaseUrl, bot.id, next);
      setBot(updated);
    } catch (err) {
      showError(err instanceof Error ? err.message : "Не удалось изменить статус бота");
    } finally {
      setTogglingEnabled(false);
    }
  };

  const enabledBanner = (
    <Banner
      variant={bot.enabled ? "success" : "warning"}
      icon={
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
          <circle cx="10" cy="10" r="9" stroke="currentColor" strokeWidth="1.5" />
          <path
            d="M6.5 10.5l2.2 2.2L14 8"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      }
      title={bot.enabled ? "Бот активен — отвечает на сообщения" : "Бот на паузе — не отвечает клиентам"}
      action={
        <Switch
          checked={bot.enabled}
          onChange={() => void handleToggleEnabled()}
          disabled={togglingEnabled}
          aria-label="Бот активен"
        />
      }
    />
  );

  if (bot.linked_at) {
    return (
      <div>
        {enabledBanner}
        <Card className="flex flex-col items-center gap-3 p-8 text-center">
          <IconBadge variant="success" size="lg">
            <svg width="28" height="28" viewBox="0 0 20 20" fill="none" aria-hidden="true">
              <path
                d="M5 10.5l3.2 3.2L15 6.5"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </IconBadge>
          <div>
            <p className="text-base font-bold text-ink">WhatsApp подключён</p>
            <p className="mt-1 font-mono text-sm text-ink-soft">{bot.phone}</p>
          </div>
          <Button variant="danger" onClick={() => void handleLogout()} disabled={loggingOut}>
            {loggingOut ? "Отключаем…" : "Отключить"}
          </Button>
        </Card>
        {pollError && (
          <p role="alert" className="mt-3 text-sm text-danger">
            {pollError}
          </p>
        )}
      </div>
    );
  }

  return (
    <div>
      {enabledBanner}
      <Card className="p-5">
        <p className="text-sm text-ink">Отсканируйте QR в WhatsApp на телефоне</p>
        {qrUrl && (
          // eslint-disable-next-line @next/next/no-img-element -- PNG отдаёт api напрямую, не статический ассет Next.js
          <img
            src={qrUrl}
            alt="QR-код для подключения WhatsApp"
            width={300}
            height={300}
            className="mt-3 rounded-lg border border-border"
          />
        )}
        {pollError && (
          <p role="alert" className="mt-3 text-sm text-danger">
            {pollError}
          </p>
        )}
      </Card>
    </div>
  );
}
```

(Изменения относительно текущего файла: новые импорты `patchBotEnabled`/
`Banner`/`IconBadge`/`Switch`; новое состояние `togglingEnabled` и
хендлер `handleToggleEnabled`; общий `enabledBanner` рендерится НАД обеими
ветками — QR и «подключён» — баннер про паузу бота актуален независимо от
состояния подключения номера. Ветка «подключён» — вместо плоской строки
`<p>Подключён: ...</p>`+кнопка теперь `IconBadge`-герой в `Card`. Ветка
QR — без структурных изменений, кроме `rounded-md`→`rounded-lg` на самом
QR-изображении (последний оставшийся `rounded-md` в проекте, см. Task 4).)

- [ ] **Step 3: Добавить `patchBotEnabled` в мок `lib/api` и два новых теста в `QrPanel.test.tsx`**

В `services/admin-web/components/QrPanel.test.tsx` в блоке `vi.mock`
добавить `patchBotEnabled: vi.fn()`:

```tsx
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    fetchBot: vi.fn(),
    logoutBot: vi.fn(),
    patchBotEnabled: vi.fn(),
  };
});
```

Append to the end of the file:

```tsx
it("toggles bot.enabled via the banner switch", async () => {
  const enabledBot = { ...linkedBot, enabled: false };
  const afterToggle = { ...linkedBot, enabled: true };
  vi.mocked(api.patchBotEnabled).mockResolvedValue(afterToggle);
  render(<QrPanel initialBot={enabledBot} apiBaseUrl="http://api" pollIntervalMs={10000} />);

  fireEvent.click(screen.getByRole("checkbox", { name: /бот активен/i }));

  await waitFor(() => {
    expect(api.patchBotEnabled).toHaveBeenCalledWith("http://api", "1", true);
  });
  expect(screen.getByText(/бот активен — отвечает/i)).toBeInTheDocument();
});

it("shows an error toast when toggling bot.enabled fails", async () => {
  vi.mocked(api.patchBotEnabled).mockRejectedValue(new Error("update failed"));
  render(<QrPanel initialBot={linkedBot} apiBaseUrl="http://api" pollIntervalMs={10000} />);

  fireEvent.click(screen.getByRole("checkbox", { name: /бот активен/i }));

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent(/update failed/i);
  });
});
```

(Существующие 5 тестов файла не переписываются — `screen.getByText(/996700000000/)`,
кнопка «Отключить», `screen.getByRole("status")`/`getByRole("alert")`
продолжают находить те же элементы в новой разметке, т.к. `IconBadge`-герой
не убирает и не переименовывает ни одного из них.)

- [ ] **Step 4: Прогнать тесты, typecheck, билд**

Run: `npx vitest run components/QrPanel.test.tsx`
Expected: PASS, 7 тестов (5 существующих + 2 новых).

Run (from `services/admin-web/`): `npm test && npx tsc --noEmit && npm run build`
Expected: всё чисто.

- [ ] **Step 5: Commit**

```bash
git add services/admin-web/lib/api.ts services/admin-web/components/QrPanel.tsx \
  services/admin-web/components/QrPanel.test.tsx
git commit -m "feat(admin-web): QrPanel icon-badge hero and bot.enabled banner toggle"
```

---

## After this plan

Спека называет Волну 3 — единый живой прогон всего кабинета на docker
compose. Учитывая, что живая проверка уже была сделана в начале ЭТОЙ
сессии (до старта Волны 2, на состоянии сразу после Волны 1) и объём
Волны 2 небольшой и чисто аддитивный (два новых визуальных элемента на
одном экране + мелкие радиус-правки), финальный живой прогон по итогам
Волны 2 может быть тем же самым шагом, что закрывает всю v2-инициативу —
отдельной Волны 3 не требуется, если прогон после Волны 2 пройдёт чисто.
