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

  // Critical finding (review round 1): admin-web session-cookie must never
  // reach api — только производный Bearer-токен. Браузер сам прикладывает
  // Cookie к запросу на "/api-proxy" (свой origin); route.ts не должен
  // форвардить этот заголовок дальше на upstream.
  it("does not forward the Cookie header to api, only the derived Bearer token", async () => {
    vi.doMock("next/headers", () => ({
      cookies: async () => ({
        get: (name: string) => (name === "session" ? { value: "test-token" } : undefined),
      }),
    }));
    const upstreamResponse = new Response("{}", { status: 200 });
    const fetchSpy = vi.spyOn(global, "fetch").mockResolvedValue(upstreamResponse);

    const { GET } = await import("./[...path]/route");
    const request = new Request("http://admin-web/api-proxy/bots", {
      headers: { Cookie: "session=test-token; other=value" },
    });
    await GET(request, { params: Promise.resolve({ path: ["bots"] }) });

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [, init] = fetchSpy.mock.calls[0];
    const forwardedHeaders = init!.headers as Headers;
    expect(forwardedHeaders.has("cookie")).toBe(false);
    expect(forwardedHeaders.get("Authorization")).toBe("Bearer test-token");
  });

  // Important #1 (review round 1): non-GET запросы с телом (multipart —
  // загрузка фото товара) должны форвардиться как есть — метод, заголовки
  // (включая Content-Type с boundary) и сырые байты тела, без пересборки.
  it("forwards a POST with a multipart body unchanged (method, Content-Type, raw bytes)", async () => {
    vi.doMock("next/headers", () => ({
      cookies: async () => ({
        get: (name: string) => (name === "session" ? { value: "test-token" } : undefined),
      }),
    }));
    const upstreamResponse = new Response(JSON.stringify({ id: "p1" }), {
      status: 201,
      headers: { "Content-Type": "application/json" },
    });
    const fetchSpy = vi.spyOn(global, "fetch").mockResolvedValue(upstreamResponse);

    const formData = new FormData();
    formData.append("name", "Product 1");
    formData.append("photo", new Blob(["fake-image-bytes"], { type: "image/png" }), "photo.png");

    const originalRequest = new Request("http://admin-web/api-proxy/products", {
      method: "POST",
      body: formData,
    });
    const originalContentType = originalRequest.headers.get("content-type");
    const expectedBytes = await originalRequest.clone().arrayBuffer();

    const { POST } = await import("./[...path]/route");
    const response = await POST(originalRequest, { params: Promise.resolve({ path: ["products"] }) });

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [, init] = fetchSpy.mock.calls[0];
    expect(init!.method).toBe("POST");
    const forwardedHeaders = init!.headers as Headers;
    expect(originalContentType).toMatch(/^multipart\/form-data; boundary=/);
    expect(forwardedHeaders.get("content-type")).toBe(originalContentType);
    expect(Buffer.from(init!.body as ArrayBuffer)).toEqual(Buffer.from(expectedBytes));
    expect(response.status).toBe(201);
  });
});
