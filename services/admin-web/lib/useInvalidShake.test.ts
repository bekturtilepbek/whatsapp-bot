import { expect, it } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useInvalidShake } from "@/lib/useInvalidShake";

it("tracks which fields are invalid and bumps shakeKey on every shake()", () => {
  const { result } = renderHook(() => useInvalidShake());

  expect(result.current.isInvalid("name")).toBe(false);
  const initialKey = result.current.shakeKey;

  act(() => result.current.shake(["name"]));
  expect(result.current.isInvalid("name")).toBe(true);
  expect(result.current.isInvalid("media")).toBe(false);
  expect(result.current.shakeKey).toBe(initialKey + 1);

  // Тот же набор полей второй раз подряд — shakeKey всё равно растёт,
  // иначе React key обёртки поля не поменяется и анимация не перезапустится.
  act(() => result.current.shake(["name"]));
  expect(result.current.shakeKey).toBe(initialKey + 2);
});

it("clear() removes a single field without touching the others", () => {
  const { result } = renderHook(() => useInvalidShake());

  act(() => result.current.shake(["name", "media"]));
  act(() => result.current.clear("name"));

  expect(result.current.isInvalid("name")).toBe(false);
  expect(result.current.isInvalid("media")).toBe(true);
});
