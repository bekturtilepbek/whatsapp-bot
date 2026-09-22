import { expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { BrandMark } from "@/components/ui/BrandMark";

it("renders the platform logo image", () => {
  render(<BrandMark />);
  expect(screen.getByRole("img", { name: /логотип платформы/i })).toBeInTheDocument();
});
