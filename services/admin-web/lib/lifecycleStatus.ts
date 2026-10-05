import type { LifecycleStatus } from "@/lib/api";

// FEATURES.md 6.22 — служебный статус клиента для владельца платформы.
// Порядок = порядок в выпадающем списке.
export const LIFECYCLE_STATUS_BADGES: Record<
  LifecycleStatus,
  { label: string; variant: "owner" | "paused" | "neutral" | "success" | "danger" }
> = {
  in_development: { label: "В разработке", variant: "owner" },
  active: { label: "Подключён", variant: "success" },
  frozen: { label: "Заморожен", variant: "neutral" },
  unpaid: { label: "Не оплачен", variant: "danger" },
};

export const LIFECYCLE_STATUSES = Object.keys(LIFECYCLE_STATUS_BADGES) as LifecycleStatus[];
