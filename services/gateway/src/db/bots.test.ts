import type { Pool } from "pg";
import { describe, expect, it, vi } from "vitest";
import {
  DEFAULT_MEDIA_MAX_SIZE_BYTES,
  getBotMediaMaxSizeBytes,
  listLinkedBotIds,
  setSessionStatus,
} from "./bots.js";

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

// Регрессия (живая проверка 2026-09-12, FEATURES.md 9.10): реально
// работающая, шлющая сообщения сессия имела auth_state.creds.registered
// = false — старое условие никогда не находило ни один привязанный бот
// при рестарте gateway. Условие должно быть на phone, не на Baileys-
// внутреннем registered-флаге.
describe("listLinkedBotIds", () => {
  it("queries by phone IS NOT NULL, not the unreliable Baileys registered flag", async () => {
    const query = vi.fn(async () => ({ rows: [{ bot_id: "bot-1" }, { bot_id: "bot-2" }] }));
    const pool = { query } as unknown as Pool;

    const result = await listLinkedBotIds(pool);

    expect(result).toEqual(["bot-1", "bot-2"]);
    const [sql] = query.mock.calls[0] as [string];
    expect(sql).toContain("phone IS NOT NULL");
    expect(sql).not.toContain("registered");
  });
});

describe("setSessionStatus", () => {
  it("upserts status and refreshes last_seen for the given bot", async () => {
    const query = vi.fn(async () => ({ rows: [] }));
    const pool = { query } as unknown as Pool;

    await setSessionStatus(pool, "bot-1", "reconnecting");

    expect(query).toHaveBeenCalledTimes(1);
    const [sql, params] = query.mock.calls[0] as [string, unknown[]];
    expect(sql).toContain("INSERT INTO bot_sessions");
    expect(sql).toContain("ON CONFLICT (bot_id) DO UPDATE");
    expect(params).toEqual(["bot-1", "reconnecting"]);
  });
});
