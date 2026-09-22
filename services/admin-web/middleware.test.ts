// @vitest-environment node
import { describe, expect, it } from "vitest";
import { NextRequest } from "next/server";
import { config, middleware } from "./middleware";

function makeRequest(path: string, cookie?: string): NextRequest {
  const headers = new Headers();
  if (cookie) headers.set("cookie", cookie);
  return new NextRequest(new Request(`http://admin-web${path}`, { headers }));
}

describe("middleware", () => {
  it("redirects to /login when there is no session cookie", () => {
    const response = middleware(makeRequest("/bots"));
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toContain("/login");
  });

  it("passes through when a session cookie is present", () => {
    const response = middleware(makeRequest("/bots", "session=token"));
    expect(response.status).toBe(200);
  });

  it("does not redirect the /login page itself", () => {
    const response = middleware(makeRequest("/login"));
    expect(response.status).toBe(200);
  });

  it("redirects an authenticated visitor away from /login", () => {
    const response = middleware(makeRequest("/login", "session=token"));
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toContain("/bots");
  });

  it("excludes the logo/icon static assets from the matcher (unauthenticated requests must not be redirected)", () => {
    // Матчер должен проверяться от начала строки — без ^ JS .test()
    // сканирует с любой позиции и находит совпадение позже в строке
    // (например, начиная сразу после "/brand/"), давая ложный "true".
    const matcherRegex = new RegExp(`^${config.matcher[0]}$`);
    expect(matcherRegex.test("/brand/logo-master.png")).toBe(false);
    expect(matcherRegex.test("/icon.png")).toBe(false);
    expect(matcherRegex.test("/apple-icon.png")).toBe(false);
    // сами страницы приложения matcher по-прежнему ловит
    expect(matcherRegex.test("/bots")).toBe(true);
  });
});
