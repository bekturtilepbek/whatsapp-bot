import { afterEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ProductsTable } from "@/components/ProductsTable";
import * as api from "@/lib/api";
import type { Product } from "@/lib/api";

const refreshMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: refreshMock }),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    deleteProduct: vi.fn(),
    fetchProducts: vi.fn(),
  };
});

const products: Product[] = [
  {
    id: "p1",
    name: "Кроссовки",
    price: "5000.00",
    sku: "NK-001",
    description: null,
    display_custom: {},
    created_at: "2026-09-10T10:00:00Z",
  },
  {
    id: "p2",
    name: "Без цены",
    price: null,
    sku: null,
    description: null,
    display_custom: {},
    created_at: "2026-09-10T10:00:00Z",
  },
];

afterEach(() => {
  vi.clearAllMocks();
});

it("renders each product's name, price and sku", () => {
  render(<ProductsTable botId="1" apiBaseUrl="http://api" products={products} pageSize={10} />);
  expect(screen.getByText("Кроссовки")).toBeInTheDocument();
  expect(screen.getByText("5000.00")).toBeInTheDocument();
  expect(screen.getByText("NK-001")).toBeInTheDocument();
  expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2); // цена и sku "Без цены"
});

it("does nothing when the delete confirmation is declined", async () => {
  vi.stubGlobal("confirm", vi.fn().mockReturnValue(false));
  render(<ProductsTable botId="1" apiBaseUrl="http://api" products={products} pageSize={10} />);

  fireEvent.click(screen.getAllByRole("button", { name: /удалить/i })[0]);

  expect(api.deleteProduct).not.toHaveBeenCalled();
  expect(screen.getByText("Кроссовки")).toBeInTheDocument();
});

it("deletes the product and removes its row after confirmation", async () => {
  vi.stubGlobal("confirm", vi.fn().mockReturnValue(true));
  vi.mocked(api.deleteProduct).mockResolvedValue(undefined);
  render(<ProductsTable botId="1" apiBaseUrl="http://api" products={products} pageSize={10} />);

  fireEvent.click(screen.getAllByRole("button", { name: /удалить/i })[0]);

  await waitFor(() => {
    expect(api.deleteProduct).toHaveBeenCalledWith("http://api", "1", "p1");
  });
  await waitFor(() => {
    expect(screen.queryByText("Кроссовки")).not.toBeInTheDocument();
  });
  expect(refreshMock).toHaveBeenCalled();
});

it("shows an error and keeps the row when deletion fails", async () => {
  vi.stubGlobal("confirm", vi.fn().mockReturnValue(true));
  vi.mocked(api.deleteProduct).mockRejectedValue(new Error("delete failed"));
  render(<ProductsTable botId="1" apiBaseUrl="http://api" products={products} pageSize={10} />);

  fireEvent.click(screen.getAllByRole("button", { name: /удалить/i })[0]);

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent(/delete failed/i);
  });
  expect(screen.getByText("Кроссовки")).toBeInTheDocument();
});

it('hides "Показать ещё" when the first page is smaller than pageSize', () => {
  render(<ProductsTable botId="1" apiBaseUrl="http://api" products={products} pageSize={10} />);
  expect(screen.queryByRole("button", { name: /показать ещё/i })).not.toBeInTheDocument();
});

it('shows "Показать ещё", loads and appends the next page, then hides once exhausted', async () => {
  render(<ProductsTable botId="1" apiBaseUrl="http://api" products={products} pageSize={2} />);
  expect(screen.getByRole("button", { name: /показать ещё/i })).toBeInTheDocument();

  const nextProduct: Product = {
    id: "p3",
    name: "Третий товар",
    price: null,
    sku: null,
    description: null,
    display_custom: {},
    created_at: "2026-09-10T10:00:00Z",
  };
  vi.mocked(api.fetchProducts).mockResolvedValue([nextProduct]);

  fireEvent.click(screen.getByRole("button", { name: /показать ещё/i }));

  await waitFor(() => {
    expect(api.fetchProducts).toHaveBeenCalledWith("http://api", "1", { limit: 2, offset: 2 });
  });
  expect(await screen.findByText("Третий товар")).toBeInTheDocument();
  // Пришло 1 < pageSize (2) — больше грузить нечего, кнопка пропадает.
  expect(screen.queryByRole("button", { name: /показать ещё/i })).not.toBeInTheDocument();
});

it('shows an error and keeps "Показать ещё" visible when loading more fails', async () => {
  render(<ProductsTable botId="1" apiBaseUrl="http://api" products={products} pageSize={2} />);
  vi.mocked(api.fetchProducts).mockRejectedValue(new Error("load more failed"));

  fireEvent.click(screen.getByRole("button", { name: /показать ещё/i }));

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent(/load more failed/i);
  });
  expect(screen.getByRole("button", { name: /показать ещё/i })).toBeInTheDocument();
});
