import { expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { BrandMark } from "@/components/ui/BrandMark";

it("renders the platform initial", () => {
  render(<BrandMark />);
  expect(screen.getByText("Б")).toBeInTheDocument();
});
