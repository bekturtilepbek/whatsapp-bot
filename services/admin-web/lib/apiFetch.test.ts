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

  // Живой баг (2026-09-28): просроченная/невалидная cookie session
  // пережила рестарт стека, middleware.ts пропустил её (проверяет только
  // присутствие, не валидность) — /bots падал в необработанный "GET /bots
  // failed: 401" вместо редиректа на /login. apiFetch должен перехватывать
  // 401 от api и уводить на /api/session-expired (там cookie реально
  // стирается — Server Component этого при рендере не может).
  it("redirects to /api/session-expired when api rejects the session cookie with 401", async () => {
    vi.doMock("next/headers", () => ({
      cookies: async () => ({
        get: (name: string) => (name === "session" ? { value: "expired-token" } : undefined),
      }),
    }));
    const redirectMock = vi.fn(() => {
      throw new Error("NEXT_REDIRECT");
    });
    vi.doMock("next/navigation", () => ({ redirect: redirectMock }));
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 401 }));
    vi.stubGlobal("fetch", fetchMock);

    const { fetchBots } = await import("./api");

    await expect(fetchBots("http://api-internal:8000")).rejects.toThrow("NEXT_REDIRECT");
    expect(redirectMock).toHaveBeenCalledWith("/api/session-expired");
  });

  // 403 ("нет доступа к этому боту"/"только для admin") — не то же самое,
  // что 401: пользователь ЗАЛОГИНЕН, просто не имеет прав. Редирект на
  // /login тут был бы неверным — страница должна сама решить, что
  // показать (см. security.py: 401 = not authenticated, 403 = forbidden).
  it("does not redirect on 403 (authenticated but forbidden, not an expired session)", async () => {
    vi.doMock("next/headers", () => ({
      cookies: async () => ({
        get: (name: string) => (name === "session" ? { value: "valid-token" } : undefined),
      }),
    }));
    const redirectMock = vi.fn();
    vi.doMock("next/navigation", () => ({ redirect: redirectMock }));
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 403 }));
    vi.stubGlobal("fetch", fetchMock);

    const { fetchBots } = await import("./api");

    await expect(fetchBots("http://api-internal:8000")).rejects.toThrow("Нет доступа к этому действию");
    expect(redirectMock).not.toHaveBeenCalled();
  });
});
