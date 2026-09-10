import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ProductForm } from "@/components/ProductForm";
import * as api from "@/lib/api";
import type { Product } from "@/lib/api";

const pushMock = vi.fn();
const refreshMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, refresh: refreshMock }),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    createProduct: vi.fn(),
    updateProduct: vi.fn(),
  };
});

const existingProduct: Product = {
  id: "p1",
  name: "Старое имя",
  price: "100.00",
  sku: "SKU-1",
  description: "Старое описание",
  display_custom: {},
  created_at: "2026-09-10T10:00:00Z",
};

afterEach(() => {
  vi.clearAllMocks();
});

it("renders an empty form in create mode", () => {
  render(<ProductForm botId="1" apiBaseUrl="http://api" />);
  expect(screen.getByLabelText(/название/i)).toHaveValue("");
});

it("renders existing values in edit mode", () => {
  render(<ProductForm botId="1" apiBaseUrl="http://api" product={existingProduct} />);
  expect(screen.getByLabelText(/название/i)).toHaveValue("Старое имя");
  expect(screen.getByLabelText(/цена/i)).toHaveValue(100);
  expect(screen.getByLabelText(/артикул/i)).toHaveValue("SKU-1");
  expect(screen.getByLabelText(/описание/i)).toHaveValue("Старое описание");
});

it("rejects an empty name without calling the api", async () => {
  render(<ProductForm botId="1" apiBaseUrl="http://api" />);
  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));

  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(api.createProduct).not.toHaveBeenCalled();
});

it("creates a product with trimmed optional fields", async () => {
  vi.mocked(api.createProduct).mockResolvedValue(existingProduct);
  render(<ProductForm botId="1" apiBaseUrl="http://api" />);

  fireEvent.change(screen.getByLabelText(/название/i), { target: { value: "Новый товар" } });
  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));

  await waitFor(() => {
    expect(api.createProduct).toHaveBeenCalledWith("http://api", "1", {
      name: "Новый товар",
      price: null,
      sku: null,
      description: null,
      display_custom: {},
    });
  });
  expect(pushMock).toHaveBeenCalledWith("/bots/1/products");
});

it("updates an existing product", async () => {
  vi.mocked(api.updateProduct).mockResolvedValue(existingProduct);
  render(<ProductForm botId="1" apiBaseUrl="http://api" product={existingProduct} />);

  fireEvent.change(screen.getByLabelText(/цена/i), { target: { value: "200" } });
  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));

  await waitFor(() => {
    expect(api.updateProduct).toHaveBeenCalledWith("http://api", "1", "p1", {
      name: "Старое имя",
      price: 200,
      sku: "SKU-1",
      description: "Старое описание",
      display_custom: {},
    });
  });
});

it("sends display_custom only when the override checkbox is on", async () => {
  vi.mocked(api.createProduct).mockResolvedValue(existingProduct);
  render(<ProductForm botId="1" apiBaseUrl="http://api" />);

  fireEvent.change(screen.getByLabelText(/название/i), { target: { value: "Товар" } });
  fireEvent.click(screen.getByLabelText(/переопределить вывод/i));
  fireEvent.click(screen.getByLabelText(/показывать цену/i));
  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));

  await waitFor(() => {
    expect(api.createProduct).toHaveBeenCalledWith(
      "http://api",
      "1",
      expect.objectContaining({
        display_custom: { show_name: true, show_description: true, show_price: false },
      }),
    );
  });
});

it("shows a hint that fields can't be cleared back to empty in edit mode", () => {
  render(<ProductForm botId="1" apiBaseUrl="http://api" product={existingProduct} />);
  expect(screen.getAllByText(/нельзя очистить обратно/i).length).toBeGreaterThan(0);
});

it("does not show the clear-field hint in create mode", () => {
  render(<ProductForm botId="1" apiBaseUrl="http://api" />);
  expect(screen.queryByText(/нельзя очистить обратно/i)).not.toBeInTheDocument();
});

it("shows an error when saving fails", async () => {
  vi.mocked(api.createProduct).mockRejectedValue(new Error("save failed"));
  render(<ProductForm botId="1" apiBaseUrl="http://api" />);

  fireEvent.change(screen.getByLabelText(/название/i), { target: { value: "Товар" } });
  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent(/save failed/i);
  });
});
