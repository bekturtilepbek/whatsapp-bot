import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createProduct,
  deleteProduct,
  fetchBot,
  fetchBots,
  fetchProduct,
  fetchProducts,
  fetchPromptVersions,
  logoutBot,
  patchBotPrompt,
  patchBotSettings,
  qrImageUrl,
  updateProduct,
} from "@/lib/api";

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

describe("patchBotPrompt", () => {
  it("PATCHes the mapped field and returns the updated bot", async () => {
    const bot = {
      id: "1",
      name: "Bot",
      enabled: true,
      phone: null,
      linked_at: null,
      system_prompt: "новый текст",
      image_prompt: null,
      pdf_prompt: null,
    };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => bot });
    vi.stubGlobal("fetch", fetchMock);

    const result = await patchBotPrompt("http://api", "1", "main", "новый текст");

    expect(result).toEqual(bot);
    expect(fetchMock).toHaveBeenCalledWith("http://api/bots/1", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ system_prompt: "новый текст" }),
    });
  });

  it("maps image and pdf kinds to their own field", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);

    await patchBotPrompt("http://api", "1", "image", "опиши фото");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://api/bots/1",
      expect.objectContaining({ body: JSON.stringify({ image_prompt: "опиши фото" }) }),
    );

    await patchBotPrompt("http://api", "1", "pdf", "изучи документ");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://api/bots/1",
      expect.objectContaining({ body: JSON.stringify({ pdf_prompt: "изучи документ" }) }),
    );
  });

  it("throws when the response is not ok", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 400 }));
    await expect(patchBotPrompt("http://api", "1", "main", "x")).rejects.toThrow();
  });
});

describe("fetchPromptVersions", () => {
  it("returns the parsed version list", async () => {
    const versions = [
      { id: "v1", body: "текст", author: "admin", created_at: "2026-09-09T10:00:00Z" },
    ];
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => versions });
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchPromptVersions("http://api", "1", "main");

    expect(result).toEqual(versions);
    expect(fetchMock).toHaveBeenCalledWith("http://api/bots/1/prompts/main/versions", {
      cache: "no-store",
    });
  });

  it("throws when the response is not ok", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 500 }));
    await expect(fetchPromptVersions("http://api", "1", "main")).rejects.toThrow();
  });
});

describe("patchBotSettings", () => {
  it("PATCHes the settings object as-is", async () => {
    const bot = {
      id: "1",
      name: "Bot",
      enabled: true,
      phone: null,
      linked_at: null,
      system_prompt: "x",
      image_prompt: null,
      pdf_prompt: null,
    };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => bot });
    vi.stubGlobal("fetch", fetchMock);

    const settings = { batch_timeout_seconds: 2, reminder_enabled: true };
    const result = await patchBotSettings("http://api", "1", settings);

    expect(result).toEqual(bot);
    expect(fetchMock).toHaveBeenCalledWith("http://api/bots/1", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ settings }),
    });
  });

  it("throws when the response is not ok", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 400 }));
    await expect(patchBotSettings("http://api", "1", {})).rejects.toThrow();
  });
});

describe("fetchProducts", () => {
  it("returns the parsed product list", async () => {
    const products = [
      {
        id: "p1",
        name: "Товар",
        price: "100.00",
        sku: null,
        description: null,
        display_custom: {},
        created_at: "2026-09-10T10:00:00Z",
      },
    ];
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => products });
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchProducts("http://api", "1");

    expect(result).toEqual(products);
    expect(fetchMock).toHaveBeenCalledWith("http://api/bots/1/products", { cache: "no-store" });
  });

  it("throws when the response is not ok", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 500 }));
    await expect(fetchProducts("http://api", "1")).rejects.toThrow();
  });
});

describe("fetchProduct", () => {
  it("returns null on 404", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 404 }));
    const result = await fetchProduct("http://api", "1", "p1");
    expect(result).toBeNull();
  });

  it("returns the product when found", async () => {
    const product = {
      id: "p1",
      name: "Товар",
      price: null,
      sku: null,
      description: null,
      display_custom: {},
      created_at: "2026-09-10T10:00:00Z",
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => product }));
    const result = await fetchProduct("http://api", "1", "p1");
    expect(result).toEqual(product);
  });
});

describe("createProduct", () => {
  it("POSTs the input and returns the created product", async () => {
    const created = {
      id: "p1",
      name: "Товар",
      price: null,
      sku: null,
      description: null,
      display_custom: {},
      created_at: "2026-09-10T10:00:00Z",
    };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => created });
    vi.stubGlobal("fetch", fetchMock);

    const result = await createProduct("http://api", "1", { name: "Товар" });

    expect(result).toEqual(created);
    expect(fetchMock).toHaveBeenCalledWith("http://api/bots/1/products", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: "Товар" }),
    });
  });

  it("throws when the response is not ok", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 422 }));
    await expect(createProduct("http://api", "1", { name: "x" })).rejects.toThrow();
  });
});

describe("updateProduct", () => {
  it("PATCHes the input and returns the updated product", async () => {
    const updated = {
      id: "p1",
      name: "Новое имя",
      price: null,
      sku: null,
      description: null,
      display_custom: {},
      created_at: "2026-09-10T10:00:00Z",
    };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => updated });
    vi.stubGlobal("fetch", fetchMock);

    const result = await updateProduct("http://api", "1", "p1", { name: "Новое имя" });

    expect(result).toEqual(updated);
    expect(fetchMock).toHaveBeenCalledWith("http://api/bots/1/products/p1", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: "Новое имя" }),
    });
  });
});

describe("deleteProduct", () => {
  it("DELETEs the product", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 204 });
    vi.stubGlobal("fetch", fetchMock);

    await deleteProduct("http://api", "1", "p1");

    expect(fetchMock).toHaveBeenCalledWith("http://api/bots/1/products/p1", { method: "DELETE" });
  });

  it("throws when the response is not ok", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 404 }));
    await expect(deleteProduct("http://api", "1", "p1")).rejects.toThrow();
  });
});
