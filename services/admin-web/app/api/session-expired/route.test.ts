// @vitest-environment node
import { describe, expect, it, vi } from "vitest";

describe("session-expired route handler", () => {
  it("deletes the session cookie and redirects to /login", async () => {
    const deleteMock = vi.fn();
    vi.doMock("next/headers", () => ({
      cookies: async () => ({ delete: deleteMock }),
    }));

    const { GET } = await import("./route");
    const request = new Request("http://admin-web/api/session-expired", {
      headers: { host: "example.com" },
    });
    const response = await GET(request);

    expect(deleteMock).toHaveBeenCalledWith("session");
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe("http://example.com/login");
  });

  // Живой баг, найден сразу после первой версии фикса: request.url внутри
  // Route Handler резолвится через bind-адрес сервера (0.0.0.0 — "next dev
  // -H 0.0.0.0"), не через Host, который реально прислал браузер/прокси —
  // редирект на "http://0.0.0.0:.../login" недостижим ни для кого снаружи.
  it("does not leak the server bind address (0.0.0.0) into the redirect", async () => {
    vi.doMock("next/headers", () => ({
      cookies: async () => ({ delete: vi.fn() }),
    }));

    const { GET } = await import("./route");
    const request = new Request("http://0.0.0.0:3000/api/session-expired", {
      headers: { host: "myapp.example.com" },
    });
    const response = await GET(request);

    expect(response.headers.get("location")).toBe("http://myapp.example.com/login");
  });
});
