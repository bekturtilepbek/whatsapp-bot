import { expect, it } from "vitest";
import { render, screen } from "@/lib/test-utils";
import NotFound from "@/app/not-found";

it("shows a Russian 404 with a way back to the bot list", () => {
  render(<NotFound />);
  expect(screen.getByText("Страница не найдена")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /к списку ботов/i })).toHaveAttribute("href", "/bots");
});
