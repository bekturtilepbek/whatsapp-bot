// Storage поверх локальной ФС — общий docker-volume с worker в dev
// (см. compose/docker-compose.dev.yml). mimeType не нужен для fs, поэтому
// не принимается — сигнатура остаётся присваиваемой к Storage.
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join, resolve, sep } from "node:path";
import type { Storage } from "./types.js";

export class FilesystemStorage implements Storage {
  constructor(private readonly root: string) {}

  async put(key: string, bytes: Buffer): Promise<void> {
    const path = join(this.root, key);
    // Fix 1 (защита на границе join): key может прийти невалидированным от
    // будущего вызывающего кода (attachMedia уже фильтрует wa_msg_id/bot_id,
    // но это отдельный слой обороны, не полагаемся только на вызывающего).
    // join() сам по себе не запрещает "../" — резолвим оба пути и проверяем
    // префикс с разделителем, чтобы "/data/media-evil" не проходил как
    // префикс "/data/media".
    const resolvedRoot = resolve(this.root);
    const resolvedPath = resolve(path);
    if (resolvedPath !== resolvedRoot && !resolvedPath.startsWith(resolvedRoot + sep)) {
      throw new Error(`storage key resolves outside root: ${key}`);
    }
    await mkdir(dirname(resolvedPath), { recursive: true });
    await writeFile(resolvedPath, bytes);
  }
}
