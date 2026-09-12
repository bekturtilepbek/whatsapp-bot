import { describe, expect, it, vi } from "vitest";
import { RETRY_BASE_DELAY_MS, RETRY_MAX_ATTEMPTS, withRetry } from "./retry.js";

function makeFakeLogger(): import("../logger.js").TransportLogger {
  const logger = {
    level: "info",
    child: () => logger,
    trace: vi.fn(),
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  };
  return logger;
}

describe("withRetry", () => {
  it("returns the result on the first successful attempt without retrying", async () => {
    const logger = makeFakeLogger();
    const fn = vi.fn(async () => "ok");

    const result = await withRetry(fn, "sendText", logger);

    expect(result).toBe("ok");
    expect(fn).toHaveBeenCalledTimes(1);
    expect(logger.warn).not.toHaveBeenCalled();
  });

  it("retries a transient failure and succeeds within the attempt budget", async () => {
    vi.useFakeTimers();
    try {
      const logger = makeFakeLogger();
      const fn = vi
        .fn<() => Promise<string>>()
        .mockRejectedValueOnce(new Error("network blip"))
        .mockResolvedValueOnce("ok");

      const promise = withRetry(fn, "sendImage", logger);
      // Первая попытка падает синхронно (в рамках текущего микротаска) —
      // продвигаем таймеры на весь backoff перед второй попыткой.
      await vi.advanceTimersByTimeAsync(RETRY_BASE_DELAY_MS);
      const result = await promise;

      expect(result).toBe("ok");
      expect(fn).toHaveBeenCalledTimes(2);
      expect(logger.warn).toHaveBeenCalledTimes(1);
      expect(logger.warn).toHaveBeenCalledWith(
        expect.objectContaining({ label: "sendImage", attempt: 1, delay: RETRY_BASE_DELAY_MS }),
        "outbound send failed, retrying",
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it(`gives up and rethrows after ${RETRY_MAX_ATTEMPTS} attempts, backing off 1s then 2s`, async () => {
    vi.useFakeTimers();
    try {
      const logger = makeFakeLogger();
      const err = new Error("permanently broken");
      const fn = vi.fn(async () => {
        throw err;
      });

      const promise = withRetry(fn, "sendDocument", logger);
      const assertion = expect(promise).rejects.toThrow("permanently broken");

      await vi.advanceTimersByTimeAsync(RETRY_BASE_DELAY_MS); // между попыткой 1 и 2
      await vi.advanceTimersByTimeAsync(RETRY_BASE_DELAY_MS * 2); // между попыткой 2 и 3
      await assertion;

      expect(fn).toHaveBeenCalledTimes(RETRY_MAX_ATTEMPTS);
      expect(logger.warn).toHaveBeenCalledTimes(RETRY_MAX_ATTEMPTS - 1);
      expect(logger.warn).toHaveBeenNthCalledWith(
        1,
        expect.objectContaining({ attempt: 1, delay: RETRY_BASE_DELAY_MS }),
        "outbound send failed, retrying",
      );
      expect(logger.warn).toHaveBeenNthCalledWith(
        2,
        expect.objectContaining({ attempt: 2, delay: RETRY_BASE_DELAY_MS * 2 }),
        "outbound send failed, retrying",
      );
    } finally {
      vi.useRealTimers();
    }
  });
});
