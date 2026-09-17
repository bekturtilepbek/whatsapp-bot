import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { SidebarNavLink } from "@/components/ui/SidebarNavLink";

vi.mock("next/navigation", () => ({
  usePathname: vi.fn(),
}));

import { usePathname } from "next/navigation";
const mockedUsePathname = vi.mocked(usePathname);

it("marks the link active with aria-current on an exact path match", () => {
  mockedUsePathname.mockReturnValue("/dashboard");
  render(<SidebarNavLink href="/dashboard">Дашборд</SidebarNavLink>);
  expect(screen.getByRole("link", { name: "Дашборд" })).toHaveAttribute("aria-current", "page");
});

it("does not mark the link active on a different path", () => {
  mockedUsePathname.mockReturnValue("/users");
  render(<SidebarNavLink href="/dashboard">Дашборд</SidebarNavLink>);
  expect(screen.getByRole("link", { name: "Дашборд" })).not.toHaveAttribute("aria-current");
});

it("matches by prefix when exact is false", () => {
  mockedUsePathname.mockReturnValue("/bots/1/settings");
  render(
    <SidebarNavLink href="/bots" exact={false}>
      Боты
    </SidebarNavLink>,
  );
  expect(screen.getByRole("link", { name: "Боты" })).toHaveAttribute("aria-current", "page");
});
