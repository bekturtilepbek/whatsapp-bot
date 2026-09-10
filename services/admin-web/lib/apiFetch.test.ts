// @vitest-environment node
//
// apiFetch — серверная ветка (typeof window === "undefined") недостижима
// под jsdom (lib/api.test.ts, jsdom определяет window глобально) — поэтому
// отдельный файл с node-окружением специально для этого теста.

import { describe, expect, it, vi, beforeEach } from "vitest";

describe("apiFetch (server-side auth header)", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllGlobals();
  });

  it("attaches the session cookie as a Bearer header on the server", async () => {
    vi.doMock("next/headers", () => ({
      cookies: async () => ({
        get: (name: string) => (name === "session" ? { value: "test-token" } : undefined),
      }),
    }));
    const fetchMock = vi.fn().mockResolvedValue(new Response("[]", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const { fetchBots } = await import("./api");
    await fetchBots("http://api-internal:8000");

    const [, init] = fetchMock.mock.calls[0];
    expect((init.headers as Headers).get("Authorization")).toBe("Bearer test-token");
  });

  it("does not add an Authorization header when there is no session cookie", async () => {
    vi.doMock("next/headers", () => ({
      cookies: async () => ({ get: () => undefined }),
    }));
    const fetchMock = vi.fn().mockResolvedValue(new Response("[]", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const { fetchBots } = await import("./api");
    await fetchBots("http://api-internal:8000");

    const [, init] = fetchMock.mock.calls[0];
    expect(init).toEqual({ cache: "no-store" });
  });
});
