import Link from "next/link";
import { notFound } from "next/navigation";
import { ProductsTable } from "@/components/ProductsTable";
import { fetchBot, fetchProducts } from "@/lib/api";
import { API_INTERNAL_URL, API_PUBLIC_URL } from "@/lib/env";

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
  const products = await fetchProducts(API_INTERNAL_URL, id);

  return (
    <main>
      <p>
        <Link href={`/bots/${id}`}>← Назад к боту</Link>
      </p>
      <h1>{bot.name} — товары</h1>
      <p>
        <Link href={`/bots/${id}/products/new`}>Добавить товар</Link>
      </p>
      <ProductsTable botId={id} apiBaseUrl={API_PUBLIC_URL} products={products} />
    </main>
  );
}
