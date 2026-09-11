import { afterEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@/lib/test-utils";
import { UsageTable } from "@/components/UsageTable";
import * as api from "@/lib/api";
import type { UsageSummary } from "@/lib/api";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    fetchUsage: vi.fn(),
  };
});

const summaries: UsageSummary[] = [
  { bot_id: "bot-1", bot_name: "Expensive Bot", tokens_in: 1000, tokens_out: 200, cost: "1.500000" },
  { bot_id: "bot-2", bot_name: "Cheap Bot", tokens_in: 100, tokens_out: 20, cost: "0.010000" },
];

afterEach(() => {
  vi.clearAllMocks();
});

it("renders each bot's tokens and cost", () => {
  render(<UsageTable apiBaseUrl="http://api" summaries={summaries} initialPeriod="30d" />);
  expect(screen.getByText("Expensive Bot")).toBeInTheDocument();
  expect(screen.getByText("1.5000")).toBeInTheDocument();
  expect(screen.getByText("Cheap Bot")).toBeInTheDocument();
  expect(screen.getByText("0.0100")).toBeInTheDocument();
});

it("shows a totals row summing across bots", () => {
  render(<UsageTable apiBaseUrl="http://api" summaries={summaries} initialPeriod="30d" />);
  expect(screen.getByText("Итого")).toBeInTheDocument();
  expect(screen.getByText("1 100")).toBeInTheDocument(); // tokens_in total
  expect(screen.getByText("220")).toBeInTheDocument(); // tokens_out total
  expect(screen.getByText("1.5100")).toBeInTheDocument(); // cost total
});

it("shows the estimate disclaimer", () => {
  render(<UsageTable apiBaseUrl="http://api" summaries={summaries} initialPeriod="30d" />);
  expect(screen.getByText(/оценка по объявленным ценам openai/i)).toBeInTheDocument();
});

it("refetches with the selected period", async () => {
  vi.mocked(api.fetchUsage).mockResolvedValue([]);
  render(<UsageTable apiBaseUrl="http://api" summaries={summaries} initialPeriod="30d" />);

  fireEvent.change(screen.getByLabelText("Период"), { target: { value: "all" } });

  await waitFor(() => {
    expect(api.fetchUsage).toHaveBeenCalledWith("http://api", "all");
  });
});

it("shows an error when refetching fails", async () => {
  vi.mocked(api.fetchUsage).mockRejectedValue(new Error("load failed"));
  render(<UsageTable apiBaseUrl="http://api" summaries={summaries} initialPeriod="30d" />);

  fireEvent.change(screen.getByLabelText("Период"), { target: { value: "7d" } });

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent(/load failed/i);
  });
});

it("renders an empty totals row when there is no usage", () => {
  render(<UsageTable apiBaseUrl="http://api" summaries={[]} initialPeriod="30d" />);
  expect(screen.getByText("Итого")).toBeInTheDocument();
  expect(screen.getByText("0.0000")).toBeInTheDocument();
});
