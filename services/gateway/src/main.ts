// Точка входа gateway: сессии Baileys, auth-state в Postgres, QR-подключение,
// мост в Redis Streams (inbound XADD, outbound consumer group).
import Fastify from "fastify";
import QRCode from "qrcode";

import { closeRedis, getRedis } from "./bus/redis.js";
import { botExists, listLinkedBotIds } from "./db/bots.js";
import { closePool, getPool } from "./db/pool.js";
import { OutboundConsumer } from "./outbound/consumer.js";
import { SessionManager } from "./session/manager.js";
import { createStorage } from "./storage/index.js";

const app = Fastify({ logger: { name: "gateway" } });
const pool = getPool();
const redis = getRedis();
const storage = createStorage();
const sessions = new SessionManager(pool, redis, app.log, storage);
const outbound = new OutboundConsumer(redis, sessions, app.log, storage);

app.get("/health", async () => ({ status: "ok" }));

app.get<{ Params: { botId: string } }>("/qr/:botId", async (request, reply) => {
  const { botId } = request.params;
  if (!(await botExists(pool, botId))) {
    return reply.code(404).send({ error: "bot not found" });
  }
  try {
    const qr = await sessions.waitForQr(botId);
    const png = await QRCode.toBuffer(qr, { type: "png" });
    return reply.type("image/png").send(png);
  } catch (err) {
    app.log.warn({ err, botId }, "qr not available");
    return reply.code(504).send({ error: "qr not available, try again" });
  }
});

// Внутренний маршрут: вызывается api-сервисом (STAGE1_CORE Блок 3),
// наружу в проде не смотрит — только api слушает публично (localhost+SSH-туннель).
app.post<{ Params: { botId: string } }>("/bots/:botId/logout", async (request, reply) => {
  const { botId } = request.params;
  if (!(await botExists(pool, botId))) {
    return reply.code(404).send({ error: "bot not found" });
  }
  await sessions.logout(botId);
  return reply.send({ status: "logged_out" });
});

async function start(): Promise<void> {
  const linkedBotIds = await listLinkedBotIds(pool);
  app.log.info({ count: linkedBotIds.length }, "starting sessions for linked bots");
  await sessions.startAllLinked(linkedBotIds);
  await outbound.start();

  const port = Number(process.env.GATEWAY_PORT ?? 8080);
  await app.listen({ port, host: "0.0.0.0" });
  app.log.info({ port }, "gateway listening");
}

async function shutdown(): Promise<void> {
  app.log.info("shutting down");
  await outbound.stop();
  await sessions.stopAll();
  await app.close();
  await closeRedis();
  await closePool();
  process.exit(0);
}

process.on("SIGTERM", () => void shutdown());
process.on("SIGINT", () => void shutdown());

start().catch((err) => {
  app.log.error(err, "gateway failed to start");
  process.exit(1);
});
