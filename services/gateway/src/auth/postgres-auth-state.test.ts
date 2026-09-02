import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import type { Pool } from "pg";
import { usePostgresAuthState } from "./postgres-auth-state.js";

/** Мок Pool поверх Map<botId, auth_state text> — эмулирует одну строку bot_sessions. */
function makeMockPool(): { pool: Pool; rows: Map<string, string>; queryCalls: string[] } {
  const rows = new Map<string, string>();
  const queryCalls: string[] = [];
  const pool = {
    query: vi.fn(async (sql: string, params: unknown[] = []) => {
      queryCalls.push(sql.trim().slice(0, 6)); // "SELECT" | "INSERT"
      if (sql.startsWith("SELECT")) {
        const botId = params[0] as string;
        const text = rows.get(botId) ?? null;
        return { rows: [{ auth_state_text: text }] };
      }
      // INSERT ... ON CONFLICT ... upsert
      const [botId, authStateJson] = params as [string, string];
      rows.set(botId, authStateJson);
      return { rows: [] };
    }),
  } as unknown as Pool;
  return { pool, rows, queryCalls };
}

describe("usePostgresAuthState", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("initialises fresh creds for a bot with no stored row", async () => {
    const { pool } = makeMockPool();
    const auth = await usePostgresAuthState(pool, "bot-1");
    expect(auth.state.creds.registered).toBe(false);
    expect(auth.state.creds.nextPreKeyId).toBe(1);
  });

  it("saveCreds persists immediately, without debounce", async () => {
    const { pool, rows, queryCalls } = makeMockPool();
    const auth = await usePostgresAuthState(pool, "bot-1");

    (auth.state.creds as { registered: boolean }).registered = true;
    await auth.saveCreds();

    expect(rows.has("bot-1")).toBe(true);
    expect(queryCalls.filter((c) => c === "INSERT")).toHaveLength(1);
    const stored = JSON.parse(rows.get("bot-1")!);
    expect(stored.creds.registered).toBe(true);
  });

  it("keys.set() debounces the write instead of flushing synchronously", async () => {
    const { pool, rows } = makeMockPool();
    const auth = await usePostgresAuthState(pool, "bot-1");

    await auth.state.keys.set({ "pre-key": { "1": { public: new Uint8Array([1, 2, 3]) } } });
    expect(rows.has("bot-1")).toBe(false); // ещё не сброшено

    await vi.advanceTimersByTimeAsync(1000);
    expect(rows.has("bot-1")).toBe(true);
  });

  it("dispose() flushes pending key writes synchronously", async () => {
    const { pool, rows } = makeMockPool();
    const auth = await usePostgresAuthState(pool, "bot-1");

    await auth.state.keys.set({ session: { "device-1": new Uint8Array([9, 9]) } });
    await auth.dispose();

    expect(rows.has("bot-1")).toBe(true);
  });

  it("round-trips Buffer/Uint8Array values via BufferJSON across reload", async () => {
    const { pool } = makeMockPool();
    const first = await usePostgresAuthState(pool, "bot-1");
    await first.state.keys.set({ "pre-key": { "7": { public: new Uint8Array([5, 6, 7]) } } });
    await first.dispose();

    const second = await usePostgresAuthState(pool, "bot-1");
    const reloaded = second.state.keys.get("pre-key", ["7"]);
    expect(Array.from(reloaded["7"].public as Uint8Array)).toEqual([5, 6, 7]);
  });

  it("keys.get() returns only requested ids that exist", async () => {
    const { pool } = makeMockPool();
    const auth = await usePostgresAuthState(pool, "bot-1");
    await auth.state.keys.set({ session: { a: new Uint8Array([1]), b: new Uint8Array([2]) } });

    const result = auth.state.keys.get("session", ["a", "missing"]);
    expect(Object.keys(result)).toEqual(["a"]);
  });
});
