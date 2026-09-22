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
    addProductMedia: vi.fn(),
    deleteProductMedia: vi.fn(),
  };
});

const existingProduct: Product = {
  id: "p1",
  name: "Старое имя",
  price: "100.00",
  sku: "SKU-1",
  description: "Старое описание",
  display_custom: {},
  media: [{ id: "ph1", position: 0, mime_type: "image/jpeg" }],
  created_at: "2026-09-10T10:00:00Z",
};

function makeFile(name = "photo.jpg"): File {
  return new File(["fake bytes"], name, { type: "image/jpeg" });
}

function makeVideoFile(name = "clip.mp4"): File {
  return new File(["fake video bytes"], name, { type: "video/mp4" });
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
  expect(screen.queryByLabelText(/артикул/i)).not.toBeInTheDocument();
  expect(screen.getByLabelText(/описание/i)).toHaveValue("Старое описание");
});

it("rejects an empty name without calling the api, marking the field invalid", async () => {
  render(<ProductForm botId="1" apiBaseUrl="http://api" />);
  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));

  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(api.createProduct).not.toHaveBeenCalled();
  expect(screen.getByLabelText(/название/i)).toHaveAttribute("aria-invalid", "true");
  // Подпись поля должна покраснеть вместе с рамкой — не только сам инпут.
  expect(screen.getByText("Название").closest("label")).toHaveClass("text-danger");
  // И трястись вместе с текстом, не только с полем ввода — оба внутри
  // одной .animate-shake обёртки.
  const shakeWrapper = document.querySelector(".animate-shake");
  expect(shakeWrapper).toContainElement(screen.getByText("Название"));
  expect(shakeWrapper).toContainElement(screen.getByLabelText(/название/i));
});

it("clears the invalid marker on the name field once the user starts typing", async () => {
  render(<ProductForm botId="1" apiBaseUrl="http://api" />);
  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));
  await screen.findByRole("alert");
  expect(screen.getByLabelText(/название/i)).toHaveAttribute("aria-invalid", "true");

  fireEvent.change(screen.getByLabelText(/название/i), { target: { value: "Т" } });

  expect(screen.getByLabelText(/название/i)).not.toHaveAttribute("aria-invalid");
});

it("rejects submit in create mode without any media, marking the field invalid", async () => {
  render(<ProductForm botId="1" apiBaseUrl="http://api" />);

  fireEvent.change(screen.getByLabelText(/название/i), { target: { value: "Товар" } });
  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));

  expect(await screen.findByRole("alert")).toHaveTextContent(/нужно хотя бы одно медиа/i);
  expect(api.createProduct).not.toHaveBeenCalled();
  expect(screen.getByText("Медиа").closest("label")).toHaveClass("text-danger");
});

it("creates a product with trimmed optional fields and the selected photo", async () => {
  vi.mocked(api.createProduct).mockResolvedValue(existingProduct);
  render(<ProductForm botId="1" apiBaseUrl="http://api" />);
  const photo = makeFile();

  fireEvent.change(screen.getByLabelText(/название/i), { target: { value: "Новый товар" } });
  fireEvent.change(screen.getByLabelText(/^медиа/i), { target: { files: [photo] } });
  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));

  await waitFor(() => {
    expect(api.createProduct).toHaveBeenCalledWith(
      "http://api",
      "1",
      { name: "Новый товар", price: null, description: null, display_custom: {} },
      [photo],
    );
  });
  expect(pushMock).toHaveBeenCalledWith("/bots/1/products");
  expect(screen.getByRole("status")).toHaveTextContent(/товар сохранён/i);
});

it("updates an existing product's text fields (media untouched by this save)", async () => {
  vi.mocked(api.updateProduct).mockResolvedValue(existingProduct);
  render(<ProductForm botId="1" apiBaseUrl="http://api" product={existingProduct} />);

  fireEvent.change(screen.getByLabelText(/цена/i), { target: { value: "200" } });
  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));

  await waitFor(() => {
    expect(api.updateProduct).toHaveBeenCalledWith("http://api", "1", "p1", {
      name: "Старое имя",
      price: 200,
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
  fireEvent.change(screen.getByLabelText(/^медиа/i), { target: { files: [makeFile()] } });
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
  fireEvent.change(screen.getByLabelText(/^медиа/i), { target: { files: [makeFile()] } });
  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent(/save failed/i);
  });
});

it("does not render a media input in edit mode (media has its own section)", () => {
  render(<ProductForm botId="1" apiBaseUrl="http://api" product={existingProduct} />);
  expect(screen.queryByLabelText(/^медиа/i)).not.toBeInTheDocument();
});

it("renders existing photos with a delete button in edit mode", () => {
  render(<ProductForm botId="1" apiBaseUrl="http://api" product={existingProduct} />);
  expect(screen.getByRole("img", { name: /медиа товара/i })).toHaveAttribute(
    "src",
    "http://api/bots/1/products/p1/media/ph1",
  );
  expect(screen.getByRole("button", { name: /^удалить$/i })).toBeInTheDocument();
});

it("renders a video item as a <video>, not an <img>", () => {
  const withVideo: Product = {
    ...existingProduct,
    media: [
      { id: "ph1", position: 0, mime_type: "image/jpeg" },
      { id: "vid1", position: 1, mime_type: "video/mp4" },
    ],
  };
  render(<ProductForm botId="1" apiBaseUrl="http://api" product={withVideo} />);

  expect(screen.getAllByRole("img", { name: /медиа товара/i })).toHaveLength(1);
  const video = document.querySelector("video");
  expect(video).not.toBeNull();
  expect(video).toHaveAttribute("src", "http://api/bots/1/products/p1/media/vid1");
});

it("disables the delete button when it is the only media item", () => {
  render(<ProductForm botId="1" apiBaseUrl="http://api" product={existingProduct} />);
  expect(screen.getByRole("button", { name: /^удалить$/i })).toBeDisabled();
});

it("enables delete and removes the item from view when there is more than one", async () => {
  const twoItems: Product = {
    ...existingProduct,
    media: [
      { id: "ph1", position: 0, mime_type: "image/jpeg" },
      { id: "ph2", position: 1, mime_type: "image/jpeg" },
    ],
  };
  vi.mocked(api.deleteProductMedia).mockResolvedValue(undefined);
  render(<ProductForm botId="1" apiBaseUrl="http://api" product={twoItems} />);

  const deleteButtons = screen.getAllByRole("button", { name: /^удалить$/i });
  expect(deleteButtons[0]).not.toBeDisabled();
  fireEvent.click(deleteButtons[0]);

  await waitFor(() => {
    expect(api.deleteProductMedia).toHaveBeenCalledWith("http://api", "1", "p1", "ph1");
  });
  await waitFor(() => {
    expect(screen.getAllByRole("img", { name: /медиа товара/i })).toHaveLength(1);
  });
  expect(screen.getByRole("status")).toHaveTextContent(/медиа удалено/i);
});

it("adds media via the file input in edit mode", async () => {
  const added = [{ id: "ph2", position: 1, mime_type: "image/jpeg" }];
  vi.mocked(api.addProductMedia).mockResolvedValue(added);
  render(<ProductForm botId="1" apiBaseUrl="http://api" product={existingProduct} />);
  const photo = makeFile("new.jpg");

  fireEvent.change(screen.getByLabelText(/добавить ещё/i), { target: { files: [photo] } });

  await waitFor(() => {
    expect(api.addProductMedia).toHaveBeenCalledWith("http://api", "1", "p1", [photo]);
  });
  await waitFor(() => {
    expect(screen.getAllByRole("img", { name: /медиа товара/i })).toHaveLength(2);
  });
  expect(screen.getByRole("status")).toHaveTextContent(/медиа добавлено/i);
});

it("adds a video via the file input in edit mode", async () => {
  const added = [{ id: "vid1", position: 1, mime_type: "video/mp4" }];
  vi.mocked(api.addProductMedia).mockResolvedValue(added);
  render(<ProductForm botId="1" apiBaseUrl="http://api" product={existingProduct} />);
  const video = makeVideoFile();

  fireEvent.change(screen.getByLabelText(/добавить ещё/i), { target: { files: [video] } });

  await waitFor(() => {
    expect(api.addProductMedia).toHaveBeenCalledWith("http://api", "1", "p1", [video]);
  });
  await waitFor(() => {
    expect(document.querySelector("video")).not.toBeNull();
  });
});
