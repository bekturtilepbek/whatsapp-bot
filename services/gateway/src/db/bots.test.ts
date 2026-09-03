import type { Pool } from "pg";
import { describe, expect, it, vi } from "vitest";
import { DEFAULT_MEDIA_MAX_SIZE_BYTES, getBotMediaMaxSizeBytes } from "./bots.js";

function makeFakePool(settings: Record<string, unknown>): Pool {
  return { query: vi.fn(async () => ({ rows: [{ settings }] })) } as unknown as Pool;
}

describe("getBotMediaMaxSizeBytes", () => {
  it("returns the configured value when settings.media_max_size_bytes is set", async () => {
    const pool = makeFakePool({ media_max_size_bytes: 5_000_000 });
    expect(await getBotMediaMaxSizeBytes(pool, "bot-1")).toBe(5_000_000);
  });

  it("returns the default when the setting is absent", async () => {
    const pool = makeFakePool({});
    expect(await getBotMediaMaxSizeBytes(pool, "bot-1")).toBe(DEFAULT_MEDIA_MAX_SIZE_BYTES);
  });

  it("returns the default when the value is not a positive number", async () => {
    const pool = makeFakePool({ media_max_size_bytes: -1 });
    expect(await getBotMediaMaxSizeBytes(pool, "bot-1")).toBe(DEFAULT_MEDIA_MAX_SIZE_BYTES);
  });
});
