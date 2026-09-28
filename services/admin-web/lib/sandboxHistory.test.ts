import { expect, it } from "vitest";
import { SANDBOX_HISTORY_LIMIT, toSandboxHistory } from "@/lib/sandboxHistory";

// Регрессия 2026-09-28: чат слал ВСЮ историю, API принимает максимум 50 —
// после ~25 обменов каждое сообщение в песочнице падало с 422.
it("sends only the most recent messages, like the real bot's 50-message window", () => {
  const messages = Array.from({ length: 80 }, (_, i) => ({
    role: i % 2 === 0 ? ("user" as const) : ("assistant" as const),
    content: `m${i}`,
    time: "12:00",
  }));

  const history = toSandboxHistory(messages);

  expect(history).toHaveLength(SANDBOX_HISTORY_LIMIT);
  expect(history.at(-1)).toEqual({ role: "assistant", content: "m79" });
  expect(history[0]).toEqual({ role: "assistant", content: `m${80 - SANDBOX_HISTORY_LIMIT}` });
});

it("keeps short histories as is, without extra fields", () => {
  const displayed = [{ role: "user" as const, content: "hi", time: "12:00" }];
  expect(toSandboxHistory(displayed)).toEqual([
    { role: "user", content: "hi" },
  ]);
});
