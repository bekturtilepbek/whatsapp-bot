import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { TabLink } from "@/components/ui/TabLink";

vi.mock("next/navigation", () => ({
  usePathname: vi.fn(),
}));

import { usePathname } from "next/navigation";
const mockedUsePathname = vi.mocked(usePathname);

it("marks the tab active with aria-current on an exact path match", () => {
  mockedUsePathname.mockReturnValue("/bots/1");
  render(<TabLink href="/bots/1">Обзор</TabLink>);
  expect(screen.getByRole("link", { name: "Обзор" })).toHaveAttribute("aria-current", "page");
});

it("does not mark the tab active on a different path", () => {
  mockedUsePathname.mockReturnValue("/bots/1/settings");
  render(<TabLink href="/bots/1">Обзор</TabLink>);
  expect(screen.getByRole("link", { name: "Обзор" })).not.toHaveAttribute("aria-current");
});

it("matches by prefix when exact is false", () => {
  mockedUsePathname.mockReturnValue("/bots/1/settings");
  render(
    <TabLink href="/bots/1/settings" exact={false}>
      Настройки
    </TabLink>,
  );
  expect(screen.getByRole("link", { name: "Настройки" })).toHaveAttribute("aria-current", "page");
});
