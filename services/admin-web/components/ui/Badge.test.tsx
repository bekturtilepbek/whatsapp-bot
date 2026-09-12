import { expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Badge } from "@/components/ui/Badge";

it("renders its children for every variant", () => {
  const { rerender } = render(<Badge variant="owner">owner</Badge>);
  expect(screen.getByText("owner")).toBeInTheDocument();
  rerender(<Badge variant="paused">на паузе</Badge>);
  expect(screen.getByText("на паузе")).toBeInTheDocument();
  rerender(<Badge>нейтральный</Badge>);
  expect(screen.getByText("нейтральный")).toBeInTheDocument();
});
