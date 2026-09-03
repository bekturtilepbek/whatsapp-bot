// Storage поверх локальной ФС — общий docker-volume с worker в dev
// (см. compose/docker-compose.dev.yml). mimeType не нужен для fs, поэтому
// не принимается — сигнатура остаётся присваиваемой к Storage.
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import type { Storage } from "./types.js";

export class FilesystemStorage implements Storage {
  constructor(private readonly root: string) {}

  async put(key: string, bytes: Buffer): Promise<void> {
    const path = join(this.root, key);
    await mkdir(dirname(path), { recursive: true });
    await writeFile(path, bytes);
  }
}
