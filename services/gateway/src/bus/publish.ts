// XADD в Redis Streams. Событие лежит одним JSON-полем "payload" в записи
// стрима — так его читает и Python-консюмер (json.loads на этом же поле).
import type { Redis } from "ioredis";
import type { Event } from "../contracts/events.js";

export async function publishEvent(
  redis: Redis,
  stream: string,
  event: Event,
): Promise<string | null> {
  return redis.xadd(stream, "*", "payload", JSON.stringify(event));
}
