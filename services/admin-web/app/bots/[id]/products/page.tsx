import Link from "next/link";
import { notFound } from "next/navigation";
import { ProductsTable } from "@/components/ProductsTable";
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
      <p>
        <Link href={`/bots/${id}`}>← Назад к боту</Link>
      </p>
      <h1>{bot.name} — товары</h1>
      <p>
        <Link href={`/bots/${id}/products/new`}>Добавить товар</Link>
      </p>
      <ProductsTable
        botId={id}
        apiBaseUrl={API_PROXY_PATH}
        products={products}
        pageSize={PRODUCTS_PAGE_SIZE}
      />
    </main>
  );
}
