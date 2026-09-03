// Storage поверх S3-совместимого хранилища (DO Spaces в проде). Таймаут на
// сам вызов — на стороне caller'а (media/download.ts, withTimeout), не здесь.
import { PutObjectCommand, type S3Client } from "@aws-sdk/client-s3";
import type { Storage } from "./types.js";

export class S3Storage implements Storage {
  constructor(
    private readonly client: S3Client,
    private readonly bucket: string,
  ) {}

  async put(key: string, bytes: Buffer, mimeType: string): Promise<void> {
    await this.client.send(
      new PutObjectCommand({ Bucket: this.bucket, Key: key, Body: bytes, ContentType: mimeType }),
    );
  }
}
