// @vitest-environment node
import { describe, expect, it } from "vitest";
import { NextRequest } from "next/server";
import { middleware } from "./middleware";

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
});
