// Точка входа gateway. На шаге 1 — только каркас и /health для healthcheck compose;
// сессии Baileys, мост в Redis Streams и идемпотентная отправка добавляются в шаге 4.
import Fastify from "fastify";

const app = Fastify({ logger: { name: "gateway" } });

app.get("/health", async () => ({ status: "ok" }));

const port = Number(process.env.GATEWAY_PORT ?? 8080);

app
  .listen({ port, host: "0.0.0.0" })
  .then(() => {
    app.log.info({ port }, "gateway listening");
  })
  .catch((err) => {
    app.log.error(err, "gateway failed to start");
    process.exit(1);
  });
