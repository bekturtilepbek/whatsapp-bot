"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { deleteProduct, fetchProducts, productMediaUrl, type Product } from "@/lib/api";
import { useToast } from "@/components/ToastProvider";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { MediaThumbnail } from "@/components/ui/MediaThumbnail";
import { Select } from "@/components/ui/Select";
import { compareNullableNumbers, SortableTh, type SortDirection } from "@/components/ui/SortableTh";
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

type ViewMode = "cards" | "table";
type SortKey = "name" | "price";

// Поиск/сортировка — клиентские, над уже загруженными rows (не новый запрос
// к API): PRODUCTS_PAGE_SIZE=100 первой страницей с запасом покрывает
// каталог типичного SMB-бота — тот же компромисс, что и офсет-пагинация
// "Показать ещё" рядом (см. её комментарий про сдвиг страницы).
const VIEW_MODE_STORAGE_KEY = "products-view-mode";

const SORT_OPTIONS: { value: `${SortKey}-${SortDirection}`; label: string }[] = [
  { value: "name-asc", label: "Название: А → Я" },
  { value: "name-desc", label: "Название: Я → А" },
  { value: "price-asc", label: "Сначала дешёвые" },
  { value: "price-desc", label: "Сначала дорогие" },
];

/** null — цена не указана или не число: такие товары всегда в конце. */
function parsePrice(price: string | null): number | null {
  if (price === null) return null;
  const parsed = Number(price);
  return Number.isFinite(parsed) ? parsed : null;
}

export function ProductsTable({ botId, apiBaseUrl, products, pageSize }: ProductsTableProps) {
  const router = useRouter();
  const { showError, showSuccess } = useToast();
  const [rows, setRows] = useState(products);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(products.length === pageSize);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");
  // Дефолт "cards" — по явному запросу пользователя (ближе к тому, что видит
  // клиент в WhatsApp); localStorage — только для того, чтобы не переспрашивать
  // при каждом заходе на вкладку, не источник истины ни для чего важного.
  const [viewMode, setViewMode] = useState<ViewMode>("cards");

  useEffect(() => {
    try {
      const stored = localStorage.getItem(VIEW_MODE_STORAGE_KEY);
      if (stored === "cards" || stored === "table") setViewMode(stored);
    } catch {
      // приватный режим/заблокированное хранилище — остаёмся на дефолте
    }
  }, []);

  function selectViewMode(mode: ViewMode): void {
    setViewMode(mode);
    try {
      localStorage.setItem(VIEW_MODE_STORAGE_KEY, mode);
    } catch {
      // не критично — просто не запомнится между заходами
    }
  }

  const visibleRows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = q === "" ? rows : rows.filter((p) => p.name.toLowerCase().includes(q));
    const sorted = [...filtered].sort((a, b) => {
      if (sortKey === "price") {
        return compareNullableNumbers(parsePrice(a.price), parsePrice(b.price), sortDirection);
      }
      const cmp = a.name.localeCompare(b.name, "ru");
      return sortDirection === "asc" ? cmp : -cmp;
    });
    return sorted;
  }, [rows, query, sortKey, sortDirection]);

  function toggleSort(key: SortKey): void {
    if (key === sortKey) {
      setSortDirection((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDirection("asc");
    }
  }

  const handleDelete = async (productId: string) => {
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
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-3">
          <Input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Поиск по названию…"
            aria-label="Поиск товаров"
            className="max-w-sm"
          />
          {/* В списке сортируют заголовки колонок; у карточек заголовков нет,
              а это вид по умолчанию — без этого select сортировка в нём
              была недоступна вовсе. */}
          {viewMode === "cards" && (
            <Select
              value={`${sortKey}-${sortDirection}`}
              onChange={(e) => {
                const [key, direction] = e.target.value.split("-") as [SortKey, SortDirection];
                setSortKey(key);
                setSortDirection(direction);
              }}
              aria-label="Сортировка"
              className="w-auto"
            >
              {SORT_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>
          )}
        </div>
        <div className="flex gap-1.5 rounded-lg border border-border bg-surface p-1">
          <button
            type="button"
            onClick={() => selectViewMode("cards")}
            aria-pressed={viewMode === "cards"}
            aria-label="Карточки"
            title="Карточки"
            className={`rounded-md p-2 transition-colors ${viewMode === "cards" ? "bg-accent text-white" : "text-ink-soft hover:text-ink"}`}
          >
            <svg width="18" height="18" viewBox="0 0 20 20" fill="none" aria-hidden="true">
              <rect x="2.5" y="2.5" width="6" height="6" rx="1.2" stroke="currentColor" strokeWidth="1.6" />
              <rect x="11.5" y="2.5" width="6" height="6" rx="1.2" stroke="currentColor" strokeWidth="1.6" />
              <rect x="2.5" y="11.5" width="6" height="6" rx="1.2" stroke="currentColor" strokeWidth="1.6" />
              <rect x="11.5" y="11.5" width="6" height="6" rx="1.2" stroke="currentColor" strokeWidth="1.6" />
            </svg>
          </button>
          <button
            type="button"
            onClick={() => selectViewMode("table")}
            aria-pressed={viewMode === "table"}
            aria-label="Список"
            title="Список"
            className={`rounded-md p-2 transition-colors ${viewMode === "table" ? "bg-accent text-white" : "text-ink-soft hover:text-ink"}`}
          >
            <svg width="18" height="18" viewBox="0 0 20 20" fill="none" aria-hidden="true">
              <rect x="2.5" y="4" width="15" height="2.2" rx="1" fill="currentColor" />
              <rect x="2.5" y="8.9" width="15" height="2.2" rx="1" fill="currentColor" />
              <rect x="2.5" y="13.8" width="15" height="2.2" rx="1" fill="currentColor" />
            </svg>
          </button>
        </div>
      </div>

      {visibleRows.length === 0 ? (
        <EmptyState title="Ничего не найдено" description="Попробуйте другой запрос." />
      ) : viewMode === "cards" ? (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
          {visibleRows.map((product) => (
            <Card key={product.id} className="flex flex-col overflow-hidden p-0">
              <div className="aspect-square bg-surface-alt">
                {product.media[0] && (
                  <MediaThumbnail
                    src={productMediaUrl(apiBaseUrl, botId, product.id, product.media[0].id)}
                    mimeType={product.media[0].mime_type}
                    alt={product.name}
                    className="h-full w-full object-cover"
                  />
                )}
              </div>
              <div className="flex flex-1 flex-col gap-2 p-3">
                <p className="text-sm font-medium text-ink" title={product.name}>
                  {product.name}
                </p>
                <p className="font-mono text-sm text-ink-soft">{product.price ?? "—"}</p>
                {/* flex-wrap: в узкой карточке (4 колонки / узкое окно) "Удалить"
                    раньше обрезался overflow-hidden карточки до "Уда…". */}
                <div className="mt-auto flex flex-wrap items-center justify-between gap-x-3 gap-y-1 pt-2">
                  <Link
                    href={`/bots/${botId}/products/${product.id}/edit`}
                    className="text-sm font-medium text-accent hover:underline"
                  >
                    Редактировать
                  </Link>
                  <button
                    type="button"
                    onClick={() => setPendingDeleteId(product.id)}
                    className="text-sm font-medium text-danger hover:underline"
                  >
                    Удалить
                  </button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      ) : (
        <Table>
          <table>
            <thead>
              <tr>
                <th />
                <SortableTh
                  label="Название"
                  active={sortKey === "name"}
                  direction={sortDirection}
                  onClick={() => toggleSort("name")}
                />
                <SortableTh
                  label="Цена"
                  active={sortKey === "price"}
                  direction={sortDirection}
                  onClick={() => toggleSort("price")}
                />
                <th />
                <th />
              </tr>
            </thead>
            <tbody>
              {visibleRows.map((product) => (
                <tr key={product.id}>
                  <td>
                    {product.media[0] && (
                      <MediaThumbnail
                        src={productMediaUrl(apiBaseUrl, botId, product.id, product.media[0].id)}
                        mimeType={product.media[0].mime_type}
                        alt={product.name}
                        className="h-12 w-12 rounded-lg object-cover"
                      />
                    )}
                  </td>
                  <td>{product.name}</td>
                  <td className="font-mono">{product.price ?? "—"}</td>
                  <td>
                    <Link
                      href={`/bots/${botId}/products/${product.id}/edit`}
                      className="font-medium text-accent hover:underline"
                    >
                      Редактировать
                    </Link>
                  </td>
                  <td>
                    <Button variant="danger" onClick={() => setPendingDeleteId(product.id)}>
                      Удалить
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Table>
      )}
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

      <ConfirmDialog
        open={pendingDeleteId !== null}
        title="Удалить товар?"
        description="Это действие необратимо — товар исчезнет из каталога бота."
        onConfirm={() => {
          const id = pendingDeleteId;
          setPendingDeleteId(null);
          if (id) void handleDelete(id);
        }}
        onCancel={() => setPendingDeleteId(null)}
      />
    </>
  );
}
