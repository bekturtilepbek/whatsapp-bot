import { notFound } from "next/navigation";
import { ProductForm } from "@/components/ProductForm";
import { fetchBot } from "@/lib/api";
import { API_INTERNAL_URL, API_PROXY_PATH } from "@/lib/env";

export default async function NewProductPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const bot = await fetchBot(API_INTERNAL_URL, id);
  if (!bot) {
    notFound();
  }

  return (
    <main>
      <ProductForm botId={id} apiBaseUrl={API_PROXY_PATH} />
    </main>
  );
}
