import { afterEach, describe, expect, it, vi } from "vitest";
import {
  addProductPhotos,
  createProduct,
  deleteProduct,
  deleteProductPhoto,
  fetchBot,
  fetchBots,
  fetchProduct,
  fetchProducts,
  fetchPromptVersions,
  logoutBot,
  patchBotPrompt,
  patchBotSettings,
  productPhotoUrl,
  qrImageUrl,
  sandboxMediaUrl,
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

  it("appends limit and offset as query params when given", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => [] });
    vi.stubGlobal("fetch", fetchMock);

    await fetchProducts("http://api", "1", { limit: 2, offset: 4 });

    expect(fetchMock).toHaveBeenCalledWith("http://api/bots/1/products?limit=2&offset=4", {
      cache: "no-store",
    });
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
  it("POSTs multipart form data with the given fields and photos", async () => {
    const created = {
      id: "p1",
      name: "Товар",
      price: null,
      sku: null,
      description: null,
      display_custom: {},
      photos: [{ id: "ph1", position: 0 }],
      created_at: "2026-09-10T10:00:00Z",
    };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => created });
    vi.stubGlobal("fetch", fetchMock);
    const photo = new File(["fake image bytes"], "photo.jpg", { type: "image/jpeg" });

    const result = await createProduct("http://api", "1", { name: "Товар" }, [photo]);

    expect(result).toEqual(created);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://api/bots/1/products");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    const body = init.body as FormData;
    expect(body.get("name")).toBe("Товар");
    expect(body.getAll("photos")).toEqual([photo]);
  });

  it("omits optional fields from the form when not provided", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        id: "p1",
        name: "Товар",
        price: null,
        sku: null,
        description: null,
        display_custom: {},
        photos: [],
        created_at: "2026-09-10T10:00:00Z",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const photo = new File(["x"], "photo.jpg", { type: "image/jpeg" });

    await createProduct("http://api", "1", { name: "Товар" }, [photo]);

    const body = fetchMock.mock.calls[0][1].body as FormData;
    expect(body.has("price")).toBe(false);
    expect(body.has("sku")).toBe(false);
    expect(body.has("description")).toBe(false);
    expect(body.has("display_custom")).toBe(false);
  });

  it("sends display_custom as a JSON string when given", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        id: "p1",
        name: "Товар",
        price: null,
        sku: null,
        description: null,
        display_custom: { show_price: false },
        photos: [],
        created_at: "2026-09-10T10:00:00Z",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const photo = new File(["x"], "photo.jpg", { type: "image/jpeg" });

    await createProduct(
      "http://api",
      "1",
      { name: "Товар", display_custom: { show_price: false } },
      [photo],
    );

    const body = fetchMock.mock.calls[0][1].body as FormData;
    expect(body.get("display_custom")).toBe(JSON.stringify({ show_price: false }));
  });

  it("throws when the response is not ok", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 422 }));
    const photo = new File(["x"], "photo.jpg", { type: "image/jpeg" });
    await expect(createProduct("http://api", "1", { name: "x" }, [photo])).rejects.toThrow();
  });
});

describe("addProductPhotos", () => {
  it("POSTs multipart photos to the sub-resource", async () => {
    const added = [{ id: "ph2", position: 1 }];
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => added });
    vi.stubGlobal("fetch", fetchMock);
    const photo = new File(["x"], "photo.jpg", { type: "image/jpeg" });

    const result = await addProductPhotos("http://api", "1", "p1", [photo]);

    expect(result).toEqual(added);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://api/bots/1/products/p1/photos");
    expect(init.method).toBe("POST");
    expect((init.body as FormData).getAll("photos")).toEqual([photo]);
  });

  it("throws when the response is not ok", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 422 }));
    const photo = new File(["x"], "photo.jpg", { type: "image/jpeg" });
    await expect(addProductPhotos("http://api", "1", "p1", [photo])).rejects.toThrow();
  });
});

describe("deleteProductPhoto", () => {
  it("DELETEs the photo", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 204 });
    vi.stubGlobal("fetch", fetchMock);

    await deleteProductPhoto("http://api", "1", "p1", "ph1");

    expect(fetchMock).toHaveBeenCalledWith("http://api/bots/1/products/p1/photos/ph1", {
      method: "DELETE",
    });
  });

  it("throws when the response is not ok", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 422 }));
    await expect(deleteProductPhoto("http://api", "1", "p1", "ph1")).rejects.toThrow();
  });
});

describe("productPhotoUrl", () => {
  it("builds the photo URL", () => {
    expect(productPhotoUrl("http://api/", "1", "p1", "ph1")).toBe(
      "http://api/bots/1/products/p1/photos/ph1",
    );
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

describe("sandboxMediaUrl", () => {
  it("builds the media URL with an encoded key and mime_type", () => {
    expect(
      sandboxMediaUrl("http://api/", "1", "bots/1/products/img 1.jpg", "image/jpeg"),
    ).toBe(
      "http://api/bots/1/sandbox/media?key=bots%2F1%2Fproducts%2Fimg%201.jpg&mime_type=image%2Fjpeg",
    );
  });
});
