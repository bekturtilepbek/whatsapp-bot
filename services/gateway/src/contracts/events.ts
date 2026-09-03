// zod-схемы контракта событий v1.
// Источник истины — docs/contracts/events.schema.json. Схемы написаны вручную
// и сверяются с JSON Schema тестом (events.test.ts), а не генерируются.
import { z } from "zod";

export const InboundText = z
  .object({
    type: z.literal("inbound.text"),
    bot_id: z.string().uuid(),
    wa_msg_id: z.string().min(1),
    chat_id: z.string().min(1),
    sender_wa_id: z.string().min(1),
    sender_lid: z.string().nullable().optional(),
    from_me: z.boolean(),
    text: z.string(),
    quoted_text: z.string().nullable().optional(),
    media_type: z.string().nullable().optional(),
    storage_key: z.string().nullable().optional(),
    mime_type: z.string().nullable().optional(),
    size_bytes: z.number().int().nullable().optional(),
    ts: z.number().int(),
  })
  .strict();
export type InboundText = z.infer<typeof InboundText>;

export const OutboundText = z
  .object({
    type: z.literal("outbound.text"),
    bot_id: z.string().uuid(),
    chat_id: z.string().min(1),
    text: z.string().min(1),
    client_msg_id: z.string().min(1),
  })
  .strict();
export type OutboundText = z.infer<typeof OutboundText>;

export const OutboundTyping = z
  .object({
    type: z.literal("outbound.typing"),
    bot_id: z.string().uuid(),
    chat_id: z.string().min(1),
    client_msg_id: z.string().min(1),
  })
  .strict();
export type OutboundTyping = z.infer<typeof OutboundTyping>;

export const SessionStatus = z
  .object({
    type: z.literal("session.status"),
    bot_id: z.string().uuid(),
    status: z.enum(["connecting", "qr", "open", "reconnecting", "logged_out"]),
    ts: z.number().int(),
  })
  .strict();
export type SessionStatus = z.infer<typeof SessionStatus>;

export const Event = z.discriminatedUnion("type", [
  InboundText,
  OutboundText,
  OutboundTyping,
  SessionStatus,
]);
export type Event = z.infer<typeof Event>;
