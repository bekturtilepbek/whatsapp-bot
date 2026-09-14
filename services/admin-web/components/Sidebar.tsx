import Link from "next/link";
import { logout } from "@/app/login/actions";
import { fetchCurrentUser } from "@/lib/currentUser";

const NAV_LINK_CLASSES = "rounded-md px-2.5 py-2 text-sm hover:bg-white/5 hover:text-sidebar-ink";

export async function Sidebar() {
  const user = await fetchCurrentUser();
  if (!user) return null;

  return (
    <aside className="flex h-screen w-[232px] shrink-0 flex-col bg-sidebar px-3.5 py-5 text-sidebar-ink-soft">
      <div className="mb-6 flex items-center gap-2 px-2">
        <span className="flex h-6 w-6 items-center justify-center rounded-md bg-accent text-xs font-semibold text-white">
          Б
        </span>
        <span className="text-sm font-semibold text-sidebar-ink">Платформа ботов</span>
      </div>

      <nav className="flex flex-col gap-0.5">
        <Link href="/bots" className={NAV_LINK_CLASSES}>
          Боты
        </Link>
      </nav>

      {user.is_platform_owner && (
        <nav className="mt-5 flex flex-col gap-0.5">
          <div className="px-2.5 pb-1.5 text-[10.5px] uppercase tracking-wide text-sidebar-ink-soft">
            Платформа
          </div>
          <Link href="/dashboard" className={NAV_LINK_CLASSES}>
            Дашборд
          </Link>
          <Link href="/users" className={NAV_LINK_CLASSES}>
            Пользователи
          </Link>
          <Link href="/audit-log" className={NAV_LINK_CLASSES}>
            Аудит-лог
          </Link>
          <Link href="/usage" className={NAV_LINK_CLASSES}>
            Расходы
          </Link>
        </nav>
      )}

      <div className="mt-auto flex items-center gap-2 border-t border-white/10 pt-3.5">
        <span className="min-w-0 flex-1 truncate text-xs text-sidebar-ink-soft">{user.email}</span>
        <form action={logout}>
          <button type="submit" className="text-xs text-sidebar-ink-soft hover:text-sidebar-ink">
            Выйти
          </button>
        </form>
      </div>
    </aside>
  );
}
