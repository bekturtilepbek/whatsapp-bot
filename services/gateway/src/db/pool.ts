// Единый pg.Pool на процесс gateway. DATABASE_URL — секреты не в git (ADR-007).
import { Pool } from "pg";

import type { TransportLogger } from "../logger.js";

let pool: Pool | undefined;

export function getPool(logger?: TransportLogger): Pool {
  if (!pool) {
    pool = new Pool({ connectionString: process.env.DATABASE_URL });
    // pg.Pool эмитит "error" от лица ЛЮБОГО простаивающего в пуле клиента
    // при сетевом сбое (сервер разорвал соединение, рестарт/остановка
    // Postgres) — без листенера Node бросает это как необработанное событие
    // и убивает ВЕСЬ процесс ("throw er; // Unhandled 'error' event"), даже
    // когда в этот момент не выполняется ни один запрос. Найдено живой
    // проверкой 2026-09-21 (docker compose stop postgres уронил gateway
    // целиком — тот же блэст-радиус на ВСЕХ ботов узла, что и в
    // gateway-auth-state-crash-bug, но через другой путь).
    pool.on("error", (err) => {
      (logger ?? console).error({ err }, "pg pool idle client error");
    });
  }
  return pool;
}

export async function closePool(): Promise<void> {
  await pool?.end();
  pool = undefined;
}
