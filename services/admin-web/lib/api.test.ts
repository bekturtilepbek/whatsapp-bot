import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchBot, fetchBots, logoutBot, qrImageUrl } from "@/lib/api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchBots", () => {
  it("returns the parsed bot list on success", async () => {
    const bots = [
      { id: "1", name: "Bot", enabled: true, phone: null, linked_at: null },
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, json: async () => bots }),
    );

    const result = await fetchBots("http://api");

    expect(result).toEqual(bots);
    expect(fetch).toHaveBeenCalledWith("http://api/bots", { cache: "no-store" });
  });

  it("throws when the response is not ok", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 500 }));
    await expect(fetchBots("http://api")).rejects.toThrow();
  });

  it("normalizes a trailing slash in baseUrl to avoid a double slash", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => [] });
    vi.stubGlobal("fetch", fetchMock);

    await fetchBots("http://api/");

    expect(fetchMock).toHaveBeenCalledWith("http://api/bots", { cache: "no-store" });
  });
});

describe("fetchBot", () => {
  it("returns null on 404", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 404 }));
    const result = await fetchBot("http://api", "1");
    expect(result).toBeNull();
  });

  it("returns the parsed bot on success", async () => {
    const bot = {
      id: "1",
      name: "Bot",
      enabled: true,
      phone: "996700000000",
      linked_at: "2026-09-09T00:00:00Z",
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => bot }));
    const result = await fetchBot("http://api", "1");
    expect(result).toEqual(bot);
  });
});

describe("logoutBot", () => {
  it("posts to the logout endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetchMock);

    await logoutBot("http://api", "1");

    expect(fetchMock).toHaveBeenCalledWith("http://api/bots/1/logout", { method: "POST" });
  });

  it("throws when the response is not ok", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 502 }));
    await expect(logoutBot("http://api", "1")).rejects.toThrow();
  });
});

describe("qrImageUrl", () => {
  it("includes a cache-busting query param", () => {
    const url = qrImageUrl("http://api", "1");
    expect(url).toMatch(/^http:\/\/api\/bots\/1\/qr\?t=\d+$/);
  });
});
