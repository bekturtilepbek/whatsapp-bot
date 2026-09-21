import { Card } from "@/components/ui/Card";

interface StatTileProps {
  label: string;
  value: number;
}

/** Простая плитка "число + подпись" — вкладка "Обзор" бота (раньше там были
 * только тумблер и QR, много пустого места; в старом проекте эти две
 * плитки как раз его заполняли). */
export function StatTile({ label, value }: StatTileProps) {
  return (
    <Card className="p-5">
      <p className="text-2xl font-bold text-ink">{value.toLocaleString("ru-RU")}</p>
      <p className="mt-1 text-sm text-ink-soft">{label}</p>
    </Card>
  );
}
