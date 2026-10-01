// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// vi.resetModules() обязателен по той же причине, что и в
// app/api-proxy/route.test.ts: без него "./actions" остаётся закэширован
// с моками next/headers и next/navigation из предыдущего теста.
beforeEach(() => {
  vi.resetModules();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("login", () => {
  it("sets the session cookie with the JWT and redirects to /bots on success", async () => {
    const setCookie = vi.fn();
    vi.doMock("next/headers", () => ({
      cookies: async () => ({ set: setCookie, delete: vi.fn() }),
      headers: async () => new Headers(),
    }));
    const redirectSpy = vi.fn();
    vi.doMock("next/navigation", () => ({ redirect: redirectSpy }));
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ token: "jwt-token-value" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    const { login } = await import("./actions");
    const formData = new FormData();
    formData.set("email", "owner@example.com");
    formData.set("password", "secret");

    await login(null, formData);

    expect(setCookie).toHaveBeenCalledWith(
      "session",
      "jwt-token-value",
      expect.objectContaining({
        httpOnly: true,
        sameSite: "lax",
        secure: false,
        maxAge: 30 * 24 * 60 * 60,
        path: "/",
      }),
    );
    expect(redirectSpy).toHaveBeenCalledWith("/bots");
  });

  it("returns an error message and does not set a cookie or redirect on failure", async () => {
    const setCookie = vi.fn();
    vi.doMock("next/headers", () => ({
      cookies: async () => ({ set: setCookie, delete: vi.fn() }),
      headers: async () => new Headers(),
    }));
    const redirectSpy = vi.fn();
    vi.doMock("next/navigation", () => ({ redirect: redirectSpy }));
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "invalid" }), { status: 401 })),
    );

    const { login } = await import("./actions");
    const formData = new FormData();
    formData.set("email", "owner@example.com");
    formData.set("password", "wrong");

    const result = await login(null, formData);

    expect(result).toBe("Неверный email или пароль");
    expect(setCookie).not.toHaveBeenCalled();
    expect(redirectSpy).not.toHaveBeenCalled();
  });

  it("sends the entered email and password to POST /auth/login", async () => {
    vi.doMock("next/headers", () => ({
      cookies: async () => ({ set: vi.fn(), delete: vi.fn() }),
      headers: async () => new Headers(),
    }));
    vi.doMock("next/navigation", () => ({ redirect: vi.fn() }));
    const fetchSpy = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ token: "t" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchSpy);

    const { login } = await import("./actions");
    const formData = new FormData();
    formData.set("email", "owner@example.com");
    formData.set("password", "secret");

    await login(null, formData);

    expect(fetchSpy).toHaveBeenCalledWith(
      expect.stringContaining("/auth/login"),
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "Content-Type": "application/json" }),
        body: JSON.stringify({ email: "owner@example.com", password: "secret" }),
      }),
    );
  });

  it("forwards the client IP from X-Forwarded-For so the api can rate-limit per IP", async () => {
    vi.doMock("next/headers", () => ({
      cookies: async () => ({ set: vi.fn(), delete: vi.fn() }),
      headers: async () => new Headers({ "x-forwarded-for": "203.0.113.7" }),
    }));
    vi.doMock("next/navigation", () => ({ redirect: vi.fn() }));
    const fetchSpy = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ token: "t" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchSpy);

    const { login } = await import("./actions");
    const formData = new FormData();
    formData.set("email", "owner@example.com");
    formData.set("password", "secret");

    await login(null, formData);

    expect(fetchSpy).toHaveBeenCalledWith(
      expect.stringContaining("/auth/login"),
      expect.objectContaining({
        headers: expect.objectContaining({ "X-Forwarded-For": "203.0.113.7" }),
      }),
    );
  });

  it("sends no X-Forwarded-For when the request carries none", async () => {
    vi.doMock("next/headers", () => ({
      cookies: async () => ({ set: vi.fn(), delete: vi.fn() }),
      headers: async () => new Headers(),
    }));
    vi.doMock("next/navigation", () => ({ redirect: vi.fn() }));
    const fetchSpy = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ token: "t" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchSpy);

    const { login } = await import("./actions");
    const formData = new FormData();
    formData.set("email", "owner@example.com");
    formData.set("password", "secret");

    await login(null, formData);

    const sentHeaders = fetchSpy.mock.calls[0][1].headers as Record<string, string>;
    expect(sentHeaders).not.toHaveProperty("X-Forwarded-For");
  });

  it("shows the api's rate-limit message on 429 instead of 'wrong password'", async () => {
    const setCookie = vi.fn();
    vi.doMock("next/headers", () => ({
      cookies: async () => ({ set: setCookie, delete: vi.fn() }),
      headers: async () => new Headers(),
    }));
    const redirectSpy = vi.fn();
    vi.doMock("next/navigation", () => ({ redirect: redirectSpy }));
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ detail: "Слишком много попыток входа. Попробуйте через 12 мин." }),
          { status: 429, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    const { login } = await import("./actions");
    const formData = new FormData();
    formData.set("email", "owner@example.com");
    formData.set("password", "secret");

    const result = await login(null, formData);

    expect(result).toBe("Слишком много попыток входа. Попробуйте через 12 мин.");
    expect(setCookie).not.toHaveBeenCalled();
    expect(redirectSpy).not.toHaveBeenCalled();
  });

  it("falls back to a generic rate-limit message when the 429 body is unreadable", async () => {
    vi.doMock("next/headers", () => ({
      cookies: async () => ({ set: vi.fn(), delete: vi.fn() }),
      headers: async () => new Headers(),
    }));
    vi.doMock("next/navigation", () => ({ redirect: vi.fn() }));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>nope</html>", { status: 429 })));

    const { login } = await import("./actions");
    const formData = new FormData();
    formData.set("email", "owner@example.com");
    formData.set("password", "secret");

    const result = await login(null, formData);

    expect(result).toBe("Слишком много попыток входа. Попробуйте позже.");
  });
});

describe("logout", () => {
  it("deletes the session cookie and redirects to /login", async () => {
    const deleteCookie = vi.fn();
    vi.doMock("next/headers", () => ({
      cookies: async () => ({ set: vi.fn(), delete: deleteCookie }),
    }));
    const redirectSpy = vi.fn();
    vi.doMock("next/navigation", () => ({ redirect: redirectSpy }));

    const { logout } = await import("./actions");
    await logout();

    expect(deleteCookie).toHaveBeenCalledWith("session");
    expect(redirectSpy).toHaveBeenCalledWith("/login");
  });
});

describe("cookie secure flag based on NODE_ENV", () => {
  it("sets secure: true when NODE_ENV is production", async () => {
    vi.stubEnv("NODE_ENV", "production");

    const setCookie = vi.fn();
    vi.doMock("next/headers", () => ({
      cookies: async () => ({ set: setCookie, delete: vi.fn() }),
      headers: async () => new Headers(),
    }));
    vi.doMock("next/navigation", () => ({ redirect: vi.fn() }));
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ token: "jwt-token-value" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    const { login } = await import("./actions");
    const formData = new FormData();
    formData.set("email", "owner@example.com");
    formData.set("password", "secret");

    await login(null, formData);

    expect(setCookie).toHaveBeenCalledWith(
      "session",
      "jwt-token-value",
      expect.objectContaining({
        secure: true,
      }),
    );
  });

  it("sets secure: false when NODE_ENV is not production", async () => {
    vi.stubEnv("NODE_ENV", "development");

    const setCookie = vi.fn();
    vi.doMock("next/headers", () => ({
      cookies: async () => ({ set: setCookie, delete: vi.fn() }),
      headers: async () => new Headers(),
    }));
    vi.doMock("next/navigation", () => ({ redirect: vi.fn() }));
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ token: "jwt-token-value" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    const { login } = await import("./actions");
    const formData = new FormData();
    formData.set("email", "owner@example.com");
    formData.set("password", "secret");

    await login(null, formData);

    expect(setCookie).toHaveBeenCalledWith(
      "session",
      "jwt-token-value",
      expect.objectContaining({
        secure: false,
      }),
    );
  });
});
