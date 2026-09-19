import { expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import BotSectionLoading from "@/app/bots/[id]/loading";

it("renders a loading indicator", () => {
  render(<BotSectionLoading />);
  expect(screen.getByRole("status", { name: /загрузка раздела/i })).toBeInTheDocument();
});
