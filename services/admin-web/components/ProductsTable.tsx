"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { deleteProduct, fetchProducts, productPhotoUrl, type Product } from "@/lib/api";
import { useToast } from "@/components/ToastProvider";

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

  return (
    <>
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
                    style={{ width: "48px", height: "48px", objectFit: "cover" }}
                  />
                )}
              </td>
              <td>{product.name}</td>
              <td>{product.price ?? "—"}</td>
              <td>{product.sku ?? "—"}</td>
              <td>
                <Link href={`/bots/${botId}/products/${product.id}/edit`}>Редактировать</Link>
              </td>
              <td>
                <button onClick={() => void handleDelete(product.id)}>Удалить</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {hasMore && (
        <button onClick={() => void handleLoadMore()} disabled={loadingMore}>
          {loadingMore ? "Загружаем…" : "Показать ещё"}
        </button>
      )}
    </>
  );
}
