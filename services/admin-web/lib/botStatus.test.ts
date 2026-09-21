import { expect, it } from "vitest";
import { toConnectionStatus } from "@/lib/botStatus";
import type { Bot } from "@/lib/api";

const baseBot: Bot = {
  id: "1",
  name: "Тест",
  enabled: true,
  phone: null,
  linked_at: null,
  system_prompt: "",
  image_prompt: null,
  pdf_prompt: null,
};

it("maps status=open to connected", () => {
  expect(toConnectionStatus({ ...baseBot, status: "open" })).toBe("connected");
});

it("maps connecting/qr/reconnecting to disconnected", () => {
  expect(toConnectionStatus({ ...baseBot, status: "connecting" })).toBe("disconnected");
  expect(toConnectionStatus({ ...baseBot, status: "qr" })).toBe("disconnected");
  expect(toConnectionStatus({ ...baseBot, status: "reconnecting" })).toBe("disconnected");
});

it("maps logged_out to disconnected even when linked_at is still set", () => {
  expect(
    toConnectionStatus({ ...baseBot, status: "logged_out", linked_at: "2026-01-01T00:00:00Z" }),
  ).toBe("disconnected");
});

it("falls back to linked_at when status is absent (older fixtures)", () => {
  expect(toConnectionStatus({ ...baseBot, linked_at: "2026-01-01T00:00:00Z" })).toBe("connected");
  expect(toConnectionStatus({ ...baseBot })).toBe("disconnected");
});
