import { describe, expect, it } from "vitest";
import { createStorage } from "./index.js";
import { FilesystemStorage } from "./filesystem.js";
import { S3Storage } from "./s3.js";

describe("createStorage", () => {
  it("defaults to FilesystemStorage when STORAGE_DRIVER is unset", () => {
    const storage = createStorage({} as NodeJS.ProcessEnv);
    expect(storage).toBeInstanceOf(FilesystemStorage);
  });

  it("returns S3Storage when STORAGE_DRIVER=s3 with a bucket", () => {
    const storage = createStorage({
      STORAGE_DRIVER: "s3",
      S3_BUCKET: "my-bucket",
      S3_ENDPOINT: "https://example.com",
      S3_REGION: "us-east-1",
      S3_ACCESS_KEY: "key",
      S3_SECRET_KEY: "secret",
    } as unknown as NodeJS.ProcessEnv);
    expect(storage).toBeInstanceOf(S3Storage);
  });

  it("throws when STORAGE_DRIVER=s3 without S3_BUCKET", () => {
    expect(() => createStorage({ STORAGE_DRIVER: "s3" } as NodeJS.ProcessEnv)).toThrow(
      /S3_BUCKET/,
    );
  });
});
