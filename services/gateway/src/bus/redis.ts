// Единый ioredis-клиент на процесс gateway.
import { Redis } from "ioredis";

let redis: Redis | undefined;

export function getRedis(): Redis {
  if (!redis) {
    redis = new Redis(process.env.REDIS_URL ?? "redis://localhost:6379/0");
  }
  return redis;
}

export async function closeRedis(): Promise<void> {
  await redis?.quit();
  redis = undefined;
}
