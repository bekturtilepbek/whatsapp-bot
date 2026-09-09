import Link from "next/link";
import type { Bot } from "@/lib/api";

interface BotsTableProps {
  bots: Bot[];
}

export function BotsTable({ bots }: BotsTableProps) {
  return (
    <table>
      <thead>
        <tr>
          <th>Имя</th>
          <th>Статус</th>
          <th>Номер</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {bots.map((bot) => (
          <tr key={bot.id}>
            <td>{bot.name}</td>
            <td>{bot.linked_at ? "Подключён" : "Не подключён"}</td>
            <td>{bot.phone ?? "—"}</td>
            <td>
              <Link href={`/bots/${bot.id}`}>Открыть</Link>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
