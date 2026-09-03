// Выбор реализации Storage по STORAGE_DRIVER=fs|s3 (default fs) — одинаковый
// паттерн на Python-стороне (libs/integrations/src/integrations/storage).
import { S3Client } from "@aws-sdk/client-s3";
import { FilesystemStorage } from "./filesystem.js";
import { S3Storage } from "./s3.js";
import type { Storage } from "./types.js";

export type { Storage } from "./types.js";

const DEFAULT_FS_ROOT = "/data/media";

export function createStorage(env: NodeJS.ProcessEnv = process.env): Storage {
  const driver = env.STORAGE_DRIVER ?? "fs";
  if (driver === "s3") {
    const bucket = env.S3_BUCKET;
    if (!bucket) throw new Error("S3_BUCKET is required when STORAGE_DRIVER=s3");
    const client = new S3Client({
      endpoint: env.S3_ENDPOINT,
      region: env.S3_REGION ?? "us-east-1",
      credentials: {
        accessKeyId: env.S3_ACCESS_KEY ?? "",
        secretAccessKey: env.S3_SECRET_KEY ?? "",
      },
    });
    return new S3Storage(client, bucket);
  }
  return new FilesystemStorage(env.STORAGE_FS_ROOT ?? DEFAULT_FS_ROOT);
}
