// Storage поверх локальной ФС — общий docker-volume с worker в dev
// (см. compose/docker-compose.dev.yml). mimeType не нужен для fs, поэтому
// не принимается — сигнатура остаётся присваиваемой к Storage.
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join, resolve, sep } from "node:path";
import type { Storage } from "./types.js";

export class FilesystemStorage implements Storage {
  constructor(private readonly root: string) {}

  private resolveWithinRoot(key: string): string {
    const resolvedRoot = resolve(this.root);
    const resolvedPath = resolve(join(this.root, key));
    if (resolvedPath !== resolvedRoot && !resolvedPath.startsWith(resolvedRoot + sep)) {
      throw new Error(`storage key resolves outside root: ${key}`);
    }
    return resolvedPath;
  }

  async put(key: string, bytes: Buffer): Promise<void> {
    const resolvedPath = this.resolveWithinRoot(key);
    await mkdir(dirname(resolvedPath), { recursive: true });
    await writeFile(resolvedPath, bytes);
  }

  async get(key: string): Promise<Buffer> {
    const resolvedPath = this.resolveWithinRoot(key);
    return readFile(resolvedPath);
  }
}
