"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { deleteProduct, type Product } from "@/lib/api";

interface ProductsTableProps {
  botId: string;
  apiBaseUrl: string;
  products: Product[];
}

export function ProductsTable({ botId, apiBaseUrl, products }: ProductsTableProps) {
  const router = useRouter();
  const [rows, setRows] = useState(products);
  const [error, setError] = useState<string | null>(null);

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
    </>
  );
}
