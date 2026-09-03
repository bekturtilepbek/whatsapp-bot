import type { S3Client } from "@aws-sdk/client-s3";
import { describe, expect, it, vi } from "vitest";
import { S3Storage } from "./s3.js";

function makeFakeClient() {
  return { send: vi.fn(async () => ({})) } as unknown as S3Client;
}

describe("S3Storage", () => {
  it("sends a PutObjectCommand with bucket, key, body and content-type", async () => {
    const client = makeFakeClient();
    const storage = new S3Storage(client, "my-bucket");

    await storage.put("bots/bot-1/media/msg-1", Buffer.from("hello"), "image/jpeg");

    expect(client.send).toHaveBeenCalledTimes(1);
    const command = (client.send as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(command.input).toMatchObject({
      Bucket: "my-bucket",
      Key: "bots/bot-1/media/msg-1",
      ContentType: "image/jpeg",
    });
    expect(Buffer.from(command.input.Body)).toEqual(Buffer.from("hello"));
  });
});
