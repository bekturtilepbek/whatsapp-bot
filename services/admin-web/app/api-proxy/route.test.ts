// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// vi.resetModules() в beforeEach обязателен: без него "./[...path]/route"
// остаётся закэширован с моком next/headers из первого теста, и doMock
// во втором тесте на уже загруженный модуль не действует (реальный fetch
// на api-internal:8000 вместо ранней 401-ветки).
beforeEach(() => {
  vi.resetModules();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("api-proxy route handler", () => {
  it("forwards GET with Authorization header and streams the response", async () => {
    vi.doMock("next/headers", () => ({
      cookies: async () => ({
        get: (name: string) => (name === "session" ? { value: "test-token" } : undefined),
      }),
    }));
    const upstreamResponse = new Response(JSON.stringify([{ id: "b1" }]), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
    const fetchSpy = vi.spyOn(global, "fetch").mockResolvedValue(upstreamResponse);

    const { GET } = await import("./[...path]/route");
    const request = new Request("http://admin-web/api-proxy/bots");
    const response = await GET(request, { params: Promise.resolve({ path: ["bots"] }) });

    expect(fetchSpy).toHaveBeenCalledWith(
      "http://localhost:8000/bots",
      expect.objectContaining({ method: "GET" }),
    );
    const [, init] = fetchSpy.mock.calls[0];
    expect((init!.headers as Headers).get("Authorization")).toBe("Bearer test-token");
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual([{ id: "b1" }]);
  });

  it("returns 401 without hitting api when there is no session cookie", async () => {
    vi.doMock("next/headers", () => ({
      cookies: async () => ({ get: () => undefined }),
    }));
    const fetchSpy = vi.spyOn(global, "fetch");

    const { GET } = await import("./[...path]/route");
    const request = new Request("http://admin-web/api-proxy/bots");
    const response = await GET(request, { params: Promise.resolve({ path: ["bots"] }) });

    expect(response.status).toBe(401);
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
