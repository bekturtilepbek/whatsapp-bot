import { mkdtemp, readFile, rm, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { FilesystemStorage } from "./filesystem.js";

describe("FilesystemStorage", () => {
  let root: string;

  beforeEach(async () => {
    root = await mkdtemp(join(tmpdir(), "storage-test-"));
  });

  afterEach(async () => {
    await rm(root, { recursive: true, force: true });
  });

  it("writes bytes to a nested key, creating directories as needed", async () => {
    const storage = new FilesystemStorage(root);
    await storage.put("bots/bot-1/media/msg-1", Buffer.from("hello"), "text/plain");

    const written = await readFile(join(root, "bots", "bot-1", "media", "msg-1"));
    expect(written.toString()).toBe("hello");
  });

  // Fix 1 (финальный review): join(root, key) сам по себе не запрещает "../" —
  // это защита на границе, которую владеет put(), на случай будущего
  // вызывающего кода, который не прогонит key через sanitize в attachMedia.
  it("throws and writes nothing outside root when the key attempts path traversal via nested dots", async () => {
    const storage = new FilesystemStorage(root);
    const key = "bots/x/media/../../../../../etc/cron.d/evil";

    await expect(storage.put(key, Buffer.from("evil"), "text/plain")).rejects.toThrow();
    await expect(stat(resolve(root, "..", "..", "..", "..", "etc", "cron.d", "evil"))).rejects.toThrow();
  });

  it("throws and writes nothing outside root for a simple sibling-escaping key", async () => {
    const storage = new FilesystemStorage(root);

    await expect(storage.put("../evil-sibling", Buffer.from("evil"), "text/plain")).rejects.toThrow();
    await expect(stat(resolve(root, "..", "evil-sibling"))).rejects.toThrow();
  });

  it("reads back bytes written by put", async () => {
    const storage = new FilesystemStorage(root);
    await storage.put("bots/bot-1/media/msg-1", Buffer.from("hello"), "text/plain");

    const bytes = await storage.get("bots/bot-1/media/msg-1");
    expect(bytes.toString()).toBe("hello");
  });

  it("throws when the key attempts path traversal via nested dots", async () => {
    const storage = new FilesystemStorage(root);
    const key = "bots/x/media/../../../../../etc/cron.d/evil";

    await expect(storage.get(key)).rejects.toThrow();
  });
});
