import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@/lib/test-utils";
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
    addProductPhotos: vi.fn(),
    deleteProductPhoto: vi.fn(),
  };
});

const existingProduct: Product = {
  id: "p1",
  name: "Старое имя",
  price: "100.00",
  sku: "SKU-1",
  description: "Старое описание",
  display_custom: {},
  photos: [{ id: "ph1", position: 0 }],
  created_at: "2026-09-10T10:00:00Z",
};

function makeFile(name = "photo.jpg"): File {
  return new File(["fake bytes"], name, { type: "image/jpeg" });
}

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

it("rejects submit in create mode without a photo", async () => {
  render(<ProductForm botId="1" apiBaseUrl="http://api" />);

  fireEvent.change(screen.getByLabelText(/название/i), { target: { value: "Товар" } });
  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));

  expect(await screen.findByRole("alert")).toHaveTextContent(/фото/i);
  expect(api.createProduct).not.toHaveBeenCalled();
});

it("creates a product with trimmed optional fields and the selected photo", async () => {
  vi.mocked(api.createProduct).mockResolvedValue(existingProduct);
  render(<ProductForm botId="1" apiBaseUrl="http://api" />);
  const photo = makeFile();

  fireEvent.change(screen.getByLabelText(/название/i), { target: { value: "Новый товар" } });
  fireEvent.change(screen.getByLabelText(/фото/i), { target: { files: [photo] } });
  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));

  await waitFor(() => {
    expect(api.createProduct).toHaveBeenCalledWith(
      "http://api",
      "1",
      { name: "Новый товар", price: null, sku: null, description: null, display_custom: {} },
      [photo],
    );
  });
  expect(pushMock).toHaveBeenCalledWith("/bots/1/products");
  expect(screen.getByRole("status")).toHaveTextContent(/товар сохранён/i);
});

it("updates an existing product's text fields (photos untouched by this save)", async () => {
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
  expect(screen.getByRole("status")).toHaveTextContent(/товар сохранён/i);
});

it("sends display_custom only when the override checkbox is on", async () => {
  vi.mocked(api.createProduct).mockResolvedValue(existingProduct);
  render(<ProductForm botId="1" apiBaseUrl="http://api" />);

  fireEvent.change(screen.getByLabelText(/название/i), { target: { value: "Товар" } });
  fireEvent.change(screen.getByLabelText(/фото/i), { target: { files: [makeFile()] } });
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
      expect.any(Array),
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
  fireEvent.change(screen.getByLabelText(/фото/i), { target: { files: [makeFile()] } });
  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent(/save failed/i);
  });
});

it("does not render a photo input in edit mode (photos have their own section)", () => {
  render(<ProductForm botId="1" apiBaseUrl="http://api" product={existingProduct} />);
  expect(screen.queryByLabelText(/^фото$/i)).not.toBeInTheDocument();
});

it("renders existing photos with a delete button in edit mode", () => {
  render(<ProductForm botId="1" apiBaseUrl="http://api" product={existingProduct} />);
  expect(screen.getByRole("img", { name: /фото товара/i })).toHaveAttribute(
    "src",
    "http://api/bots/1/products/p1/photos/ph1",
  );
  expect(screen.getByRole("button", { name: /удалить фото/i })).toBeInTheDocument();
});

it("disables the delete button when it is the only photo", () => {
  render(<ProductForm botId="1" apiBaseUrl="http://api" product={existingProduct} />);
  expect(screen.getByRole("button", { name: /удалить фото/i })).toBeDisabled();
});

it("enables delete and removes the photo from view when there is more than one", async () => {
  const twoPhotos: Product = {
    ...existingProduct,
    photos: [
      { id: "ph1", position: 0 },
      { id: "ph2", position: 1 },
    ],
  };
  vi.mocked(api.deleteProductPhoto).mockResolvedValue(undefined);
  render(<ProductForm botId="1" apiBaseUrl="http://api" product={twoPhotos} />);

  const deleteButtons = screen.getAllByRole("button", { name: /удалить фото/i });
  expect(deleteButtons[0]).not.toBeDisabled();
  fireEvent.click(deleteButtons[0]);

  await waitFor(() => {
    expect(api.deleteProductPhoto).toHaveBeenCalledWith("http://api", "1", "p1", "ph1");
  });
  await waitFor(() => {
    expect(screen.getAllByRole("img", { name: /фото товара/i })).toHaveLength(1);
  });
  expect(screen.getByRole("status")).toHaveTextContent(/фото удалено/i);
});

it("adds a photo via the file input in edit mode", async () => {
  const added = [{ id: "ph2", position: 1 }];
  vi.mocked(api.addProductPhotos).mockResolvedValue(added);
  render(<ProductForm botId="1" apiBaseUrl="http://api" product={existingProduct} />);
  const photo = makeFile("new.jpg");

  fireEvent.change(screen.getByLabelText(/добавить ещё/i), { target: { files: [photo] } });

  await waitFor(() => {
    expect(api.addProductPhotos).toHaveBeenCalledWith("http://api", "1", "p1", [photo]);
  });
  await waitFor(() => {
    expect(screen.getAllByRole("img", { name: /фото товара/i })).toHaveLength(2);
  });
  expect(screen.getByRole("status")).toHaveTextContent(/фото добавлено/i);
});
