import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
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
});
