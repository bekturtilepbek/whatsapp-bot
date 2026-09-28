// FEATURES.md 8.4: страховка процесса от ещё не найденных источников
// необработанных ошибок. Уже дважды находили конкретные места
// (postgres-auth-state.ts, pg.Pool/ioredis "error"), где одна ошибка роняла
// ВЕСЬ gateway — то есть сессии всех ботов на узле разом (ADR-005). Сами
// источники закрыты точечно; здесь — сетка на будущие.

interface SafetyLogger {
  error(obj: unknown, msg?: string): void;
  fatal(obj: unknown, msg?: string): void;
}

interface ProcessLike {
  on(event: string, listener: (...args: unknown[]) => void): unknown;
}

export function installProcessSafetyNet(
  proc: ProcessLike,
  logger: SafetyLogger,
  exit: (code: number) => void,
): void {
  // Отклонённый промис без обработчика — обычно сбой одной операции одного
  // бота (запись в БД, отправка). Node >= 15 по умолчанию убивает на этом
  // процесс; нам выгоднее залогировать и оставить остальные сессии жить.
  proc.on("unhandledRejection", (reason) => {
    logger.error({ err: reason }, "unhandled promise rejection");
  });

  // Синхронное исключение, долетевшее до верха стека, — состояние процесса
  // уже не гарантировано (Node docs прямо советуют не продолжать). Логируем
  // и выходим: в проде restart: unless-stopped поднимет gateway, сессии
  // восстановятся из auth-state в Postgres без QR.
  proc.on("uncaughtException", (err) => {
    logger.fatal({ err }, "uncaught exception, exiting");
    exit(1);
  });
}
