"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { deleteProduct, fetchProducts, type Product } from "@/lib/api";

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
  const [rows, setRows] = useState(products);
  const [error, setError] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(products.length === pageSize);

  const handleDelete = async (productId: string) => {
    if (!confirm("Удалить товар?")) {
      return;
    }
    setError(null);
    try {
      await deleteProduct(apiBaseUrl, botId, productId);
      setRows((current) => current.filter((p) => p.id !== productId));
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось удалить");
    }
  };

  const handleLoadMore = async () => {
    setError(null);
    setLoadingMore(true);
    try {
      const next = await fetchProducts(apiBaseUrl, botId, {
        limit: pageSize,
        offset: rows.length,
      });
      setRows((current) => [...current, ...next]);
      setHasMore(next.length === pageSize);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить ещё");
    } finally {
      setLoadingMore(false);
    }
  };

  return (
    <>
      {error && (
        <p role="alert" style={{ color: "crimson" }}>
          {error}
        </p>
      )}
      <table>
        <thead>
          <tr>
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
