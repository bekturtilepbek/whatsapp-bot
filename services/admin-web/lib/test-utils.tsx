// Общая обёртка для тестов компонентов: монтирует ToastProvider вокруг
// тестируемого дерева — useToast() бросает вне провайдера (components/
// ToastProvider.tsx), а после FEATURES.md 6.5 его используют почти все
// формы кабинета. Импортировать render/screen/... отсюда, а не напрямую
// из @testing-library/react.
//
// НЕ `export * from "@testing-library/react"` — эмпирически проверено
// (см. git history этого файла), что в этой сборке (Vite/esbuild) звёздный
// реэкспорт молча ПЕРЕКРЫВАЕТ локальный export function render(...) версией
// из testing-library (render === исходный rtlRender), вопреки спеке ES
// modules, где локальный экспорт должен побеждать. Экспортируем нужное
// явно, чтобы конфликта имён не возникало вообще.

import { render as rtlRender, type RenderOptions } from "@testing-library/react";
import type { ReactElement } from "react";
import { ToastProvider } from "@/components/ToastProvider";

export function render(ui: ReactElement, options?: Omit<RenderOptions, "wrapper">) {
  return rtlRender(ui, { wrapper: ToastProvider, ...options });
}

export {
  act,
  fireEvent,
  screen,
  waitFor,
  waitForElementToBeRemoved,
  within,
} from "@testing-library/react";
