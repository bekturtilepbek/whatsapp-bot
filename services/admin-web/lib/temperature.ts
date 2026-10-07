import type { Temperature } from "@/lib/api";

// FEATURES.md 6.13 — температура клиента (оценка диалога моделью).
export const TEMPERATURE_BADGES: Record<
  Temperature,
  { label: string; variant: "danger" | "paused" | "neutral" }
> = {
  hot: { label: "горячий", variant: "danger" },
  warm: { label: "тёплый", variant: "paused" },
  cold: { label: "холодный", variant: "neutral" },
};
