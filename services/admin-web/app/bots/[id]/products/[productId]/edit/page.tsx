import Link from "next/link";
import { notFound } from "next/navigation";
import { ProductForm } from "@/components/ProductForm";
import { fetchBot, fetchProduct } from "@/lib/api";
import { API_INTERNAL_URL, API_PUBLIC_URL } from "@/lib/env";

export default async function EditProductPage({
  params,
}: {
  params: Promise<{ id: string; productId: string }>;
}) {
  const { id, productId } = await params;
  const bot = await fetchBot(API_INTERNAL_URL, id);
  if (!bot) {
    notFound();
  }
  const product = await fetchProduct(API_INTERNAL_URL, id, productId);
  if (!product) {
    notFound();
  }

  return (
    <main>
      <p>
        <Link href={`/bots/${id}/products`}>← Назад к товарам</Link>
      </p>
      <h1>{bot.name} — редактировать товар</h1>
      <ProductForm botId={id} apiBaseUrl={API_PUBLIC_URL} product={product} />
    </main>
  );
}
