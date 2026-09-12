import { expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusPulse } from "@/components/ui/StatusPulse";

it("shows the Russian label for each status", () => {
  const { rerender } = render(<StatusPulse status="connected" />);
  expect(screen.getByText("Подключён")).toBeInTheDocument();
  rerender(<StatusPulse status="pending" />);
  expect(screen.getByText("Ждёт QR")).toBeInTheDocument();
  rerender(<StatusPulse status="disconnected" />);
  expect(screen.getByText("Не подключён")).toBeInTheDocument();
});
