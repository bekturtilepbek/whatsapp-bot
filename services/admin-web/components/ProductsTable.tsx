"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { deleteProduct, fetchProducts, productMediaUrl, type Product } from "@/lib/api";
import { useToast } from "@/components/ToastProvider";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { MediaThumbnail } from "@/components/ui/MediaThumbnail";
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
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);

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
      <Table>
        <table>
          <thead>
            <tr>
              <th />
              <th>Название</th>
              <th>Цена</th>
              <th />
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((product) => (
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
