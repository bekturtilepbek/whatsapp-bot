import Link from "next/link";
import { notFound } from "next/navigation";
import { ProductForm } from "@/components/ProductForm";
import { fetchBot } from "@/lib/api";
import { API_INTERNAL_URL, API_PUBLIC_URL } from "@/lib/env";

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
      <p>
        <Link href={`/bots/${id}/products`}>← Назад к товарам</Link>
      </p>
      <h1>{bot.name} — новый товар</h1>
      <ProductForm botId={id} apiBaseUrl={API_PUBLIC_URL} />
    </main>
  );
}
