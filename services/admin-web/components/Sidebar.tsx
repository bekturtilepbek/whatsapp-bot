import { logout } from "@/app/login/actions";
import { fetchCurrentUser } from "@/lib/currentUser";
import { BrandMark } from "@/components/ui/BrandMark";
import { SidebarNavLink } from "@/components/ui/SidebarNavLink";

export async function Sidebar() {
  const user = await fetchCurrentUser();
  if (!user) return null;

  return (
    <aside className="sticky top-0 flex h-screen w-[272px] shrink-0 flex-col border-r border-border bg-surface px-3.5 py-5">
      <div className="mb-6 flex items-center gap-2 px-2">
        <BrandMark />
        <span className="text-sm font-bold text-ink">Платформа ботов</span>
      </div>

      <nav aria-label="Основная" className="flex flex-col gap-0.5">
        <SidebarNavLink href="/bots" exact={false}>
          Боты
        </SidebarNavLink>
      </nav>

      {user.is_platform_owner && (
        <nav aria-label="Платформа" className="mt-5 flex flex-col gap-0.5">
          <div className="px-2.5 pb-1.5 text-[10.5px] font-bold uppercase tracking-wider text-ink-faint">
            Платформа
          </div>
          <SidebarNavLink href="/dashboard">Дашборд</SidebarNavLink>
          <SidebarNavLink href="/users">Пользователи</SidebarNavLink>
          <SidebarNavLink href="/audit-log">Аудит-лог</SidebarNavLink>
          <SidebarNavLink href="/usage">Расходы</SidebarNavLink>
        </nav>
      )}

      <div className="mt-auto flex items-center gap-2 border-t border-border pt-3.5">
        <span className="min-w-0 flex-1 truncate text-xs text-ink-soft">{user.email}</span>
        <form action={logout}>
          <button type="submit" className="p-0 text-xs text-ink-soft hover:text-ink">
            Выйти
          </button>
        </form>
      </div>
    </aside>
  );
}
