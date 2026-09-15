import { notFound } from "next/navigation";
import { ProductForm } from "@/components/ProductForm";
import { fetchBot, fetchProduct } from "@/lib/api";
import { API_INTERNAL_URL, API_PROXY_PATH } from "@/lib/env";

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
      <ProductForm botId={id} apiBaseUrl={API_PROXY_PATH} product={product} />
    </main>
  );
}
