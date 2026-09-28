import Link from "next/link";
import { EmptyState } from "@/components/ui/EmptyState";

/** Своя 404 вместо стандартной английской "This page could not be found" —
 * её видят на чужом/несуществующем боте или товаре (fetchBot/fetchProduct
 * отдают null на 403/404/422 → notFound()). */
export default function NotFound() {
  return (
    <div className="mx-auto max-w-lg pt-16">
      <EmptyState
        title="Страница не найдена"
        description="Возможно, её удалили, ссылка устарела или у вас нет к ней доступа."
        action={
          <Link href="/bots" className="text-sm font-medium text-accent hover:underline">
            К списку ботов
          </Link>
        }
      />
    </div>
  );
}
