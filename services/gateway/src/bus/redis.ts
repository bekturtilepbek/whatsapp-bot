// Единый ioredis-клиент на процесс gateway.
import { Redis } from "ioredis";

import type { TransportLogger } from "../logger.js";

let redis: Redis | undefined;

export function getRedis(logger?: TransportLogger): Redis {
  if (!redis) {
    redis = new Redis(process.env.REDIS_URL ?? "redis://localhost:6379/0");
    // ioredis эмитит "error" на каждой неудачной попытке (пере)подключения —
    // тот же класс риска, что и pg.Pool в db/pool.ts: без листенера Node
    // бросает необработанное событие "error" и убивает ВЕСЬ процесс на
    // первом же сетевом сбое к Redis, даже с работающей встроенной логикой
    // реконнекта (она НЕ подавляет событие "error" сама по себе).
    redis.on("error", (err) => {
      (logger ?? console).error({ err }, "redis client error");
    });
  }
  return redis;
}

export async function closeRedis(): Promise<void> {
  await redis?.quit();
  redis = undefined;
}
