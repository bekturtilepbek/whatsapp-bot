import { notFound, redirect } from "next/navigation";
import { BotSettingsForm } from "@/components/BotSettingsForm";
import { LifecycleStatusForm } from "@/components/LifecycleStatusForm";
import { RenameBotForm } from "@/components/RenameBotForm";
import { ResponsibleUserForm } from "@/components/ResponsibleUserForm";
import { TelegramLeadToolForm } from "@/components/TelegramLeadToolForm";
import { Card } from "@/components/ui/Card";
import { DEFAULT_BOT_SETTINGS, fetchBot, fetchBotTools, fetchPrompters } from "@/lib/api";
import { fetchCurrentUser, PLATFORM_WIDE_ROLES } from "@/lib/currentUser";
import { API_INTERNAL_URL, API_PROXY_PATH } from "@/lib/env";

export default async function BotSettingsPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  // client урезан (FullBotAccess) — бэкенд и так отклоняет fetchBotTools
  // 403-м, но без этой проверки страница падает страшным Next.js error
  // overlay вместо аккуратного редиректа (тот же паттерн, что у /users).
  const user = await fetchCurrentUser();
  if (user?.role === "client") {
    redirect(`/bots/${id}`);
  }
  // GET /users/prompters — PlatformWide-only (superadmin/admin), в отличие
  // от остального этой страницы (FullBotAccess, доступно и prompter). Без
  // этой проверки prompter падал в необработанный "403" при заходе на
  // Настройки — сама секция "Ответственный" ниже тоже скрыта для них же
  // (security review, 2026-09-28).
  const isPlatformWide = user !== null && PLATFORM_WIDE_ROLES.includes(user.role);
  const [bot, tools, prompters] = await Promise.all([
    fetchBot(API_INTERNAL_URL, id),
    fetchBotTools(API_INTERNAL_URL, id),
    isPlatformWide ? fetchPrompters(API_INTERNAL_URL) : Promise.resolve([]),
  ]);
  if (!bot) {
    notFound();
  }

  // Шаллоу-спред достаточен для всех полей, кроме product_display: это
  // вложенный объект, и {...DEFAULT, ...bot.settings} заменил бы его
  // ЦЕЛИКОМ, даже если на боте задан только один из трёх ключей — оставшиеся
  // потерялись бы из формы (хотя бэкенд их видит как true по умолчанию,
  // product_search.py::_resolve_display_config). Мержим этот подобъект
  // отдельно, на уровень глубже.
  const initialSettings = {
    ...DEFAULT_BOT_SETTINGS,
    ...bot.settings,
    product_display: {
      ...DEFAULT_BOT_SETTINGS.product_display,
      ...bot.settings?.product_display,
    },
  };
  const telegramLeadBinding = tools.find((t) => t.tool_name === "send_telegram_lead") ?? null;

  return (
    <main className="space-y-5">
      <Card className="p-5">
        <h2 className="mb-4 text-[15px] font-semibold text-ink">Название</h2>
        <RenameBotForm botId={id} apiBaseUrl={API_PROXY_PATH} initialName={bot.name} />
      </Card>
      {isPlatformWide && (
        <Card className="p-5">
          <h2 className="mb-4 text-[15px] font-semibold text-ink">Ответственный</h2>
          <ResponsibleUserForm
            botId={id}
            apiBaseUrl={API_PROXY_PATH}
            initialResponsibleUserId={bot.responsible_user_id ?? null}
            prompters={prompters}
          />
        </Card>
      )}
      {isPlatformWide && (
        <Card className="p-5">
          <h2 className="mb-4 text-[15px] font-semibold text-ink">Статус клиента</h2>
          <LifecycleStatusForm
            botId={id}
            apiBaseUrl={API_PROXY_PATH}
            initialStatus={bot.lifecycle_status ?? "in_development"}
          />
        </Card>
      )}
      <BotSettingsForm botId={id} apiBaseUrl={API_PROXY_PATH} initialSettings={initialSettings} />
      <TelegramLeadToolForm
        botId={id}
        apiBaseUrl={API_PROXY_PATH}
        initialBinding={telegramLeadBinding}
      />
    </main>
  );
}
