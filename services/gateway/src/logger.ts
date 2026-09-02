// Минимальный интерфейс логгера, которого хватает и Baileys (его ILogger не
// экспортируется из пакета), и pino/Fastify-логгеру — структурно совместимы.
export interface TransportLogger {
  level: string;
  child(obj: Record<string, unknown>): TransportLogger;
  trace(obj: unknown, msg?: string): void;
  debug(obj: unknown, msg?: string): void;
  info(obj: unknown, msg?: string): void;
  warn(obj: unknown, msg?: string): void;
  error(obj: unknown, msg?: string): void;
}
