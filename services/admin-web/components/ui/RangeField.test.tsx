import { expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@/lib/test-utils";
import { RangeField } from "@/components/ui/RangeField";

function setup(onCommit = vi.fn()) {
  render(
    <RangeField
      label="Батчинг"
      unit="сек"
      min={1}
      max={20}
      step={1}
      value={4}
      onCommit={onCommit}
      hint={(v) => `Ждёт ${v} с тишины`}
    />,
  );
  return { slider: screen.getByRole("slider", { name: /батчинг/i }), onCommit };
}

it("shows the current value with its unit and a hint", () => {
  setup();
  expect(screen.getByText("4 сек")).toBeInTheDocument();
  expect(screen.getByText("Ждёт 4 с тишины")).toBeInTheDocument();
});

it("updates the displayed value while dragging but commits only on release", () => {
  const { slider, onCommit } = setup();
  fireEvent.change(slider, { target: { value: "9" } });
  expect(screen.getByText("9 сек")).toBeInTheDocument();
  expect(onCommit).not.toHaveBeenCalled(); // не на каждый шаг

  fireEvent.pointerUp(slider);
  expect(onCommit).toHaveBeenCalledWith(9);
});

it("commits after keyboard changes too", () => {
  const { slider, onCommit } = setup();
  fireEvent.change(slider, { target: { value: "5" } });
  fireEvent.keyUp(slider, { key: "ArrowRight" });
  expect(onCommit).toHaveBeenCalledWith(5);
});

it("does not commit when the value did not change", () => {
  const { slider, onCommit } = setup();
  fireEvent.pointerUp(slider);
  expect(onCommit).not.toHaveBeenCalled();
});
