import { EventEmitter } from "node:events";
import { describe, expect, it, vi } from "vitest";
import { installProcessSafetyNet } from "./processSafety.js";

function setup() {
  const proc = new EventEmitter();
  const logger = { error: vi.fn(), fatal: vi.fn() };
  const exit = vi.fn();
  installProcessSafetyNet(proc, logger, exit);
  return { proc, logger, exit };
}

describe("installProcessSafetyNet (FEATURES.md 8.4)", () => {
  it("logs an unhandled rejection and keeps the process (all bots' sessions) alive", () => {
    const { proc, logger, exit } = setup();
    proc.emit("unhandledRejection", new Error("pg down"));

    expect(logger.error).toHaveBeenCalledWith(
      expect.objectContaining({ err: expect.any(Error) }),
      "unhandled promise rejection",
    );
    expect(exit).not.toHaveBeenCalled();
  });

  it("logs an uncaught exception and exits with 1 (process state is no longer trustworthy)", () => {
    const { proc, logger, exit } = setup();
    proc.emit("uncaughtException", new Error("boom"));

    expect(logger.fatal).toHaveBeenCalledWith(
      expect.objectContaining({ err: expect.any(Error) }),
      "uncaught exception, exiting",
    );
    expect(exit).toHaveBeenCalledWith(1);
  });
});
