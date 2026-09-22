import { afterEach, beforeEach, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ThemeToggle } from "@/components/ThemeToggle";

beforeEach(() => {
  document.documentElement.removeAttribute("data-theme");
  localStorage.clear();
});

afterEach(() => {
  document.documentElement.removeAttribute("data-theme");
});

it("starts in light mode by default (no saved/pre-set theme)", () => {
  render(<ThemeToggle />);
  expect(screen.getByRole("button", { name: "Включить тёмную тему" })).toBeInTheDocument();
  expect(document.documentElement).not.toHaveAttribute("data-theme");
});

it("switches to dark on click: sets the attribute and persists to localStorage", () => {
  render(<ThemeToggle />);

  fireEvent.click(screen.getByRole("button", { name: "Включить тёмную тему" }));

  expect(document.documentElement).toHaveAttribute("data-theme", "dark");
  expect(localStorage.getItem("theme")).toBe("dark");
  expect(screen.getByRole("button", { name: "Включить светлую тему" })).toBeInTheDocument();
});

it("switches back to light on a second click: removes the attribute, updates storage", () => {
  render(<ThemeToggle />);
  const button = screen.getByRole("button");

  fireEvent.click(button); // -> dark
  fireEvent.click(button); // -> light

  expect(document.documentElement).not.toHaveAttribute("data-theme");
  expect(localStorage.getItem("theme")).toBe("light");
  expect(screen.getByRole("button", { name: "Включить тёмную тему" })).toBeInTheDocument();
});

it("syncs its displayed state with an attribute already set before mount (by the anti-FOUC inline script)", () => {
  document.documentElement.setAttribute("data-theme", "dark");

  render(<ThemeToggle />);

  expect(screen.getByRole("button", { name: "Включить светлую тему" })).toBeInTheDocument();
});
