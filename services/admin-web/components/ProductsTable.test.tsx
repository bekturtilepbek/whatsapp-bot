import { afterEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@/lib/test-utils";
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
    media: [{ id: "ph1", position: 0, mime_type: "image/jpeg" }],
    created_at: "2026-09-10T10:00:00Z",
  },
  {
    id: "p2",
    name: "Без цены",
    price: null,
    sku: null,
    description: null,
    display_custom: {},
    media: [],
    created_at: "2026-09-10T10:00:00Z",
  },
];

afterEach(() => {
  vi.clearAllMocks();
});

it("renders each product's name and price", () => {
  render(<ProductsTable botId="1" apiBaseUrl="http://api" products={products} pageSize={10} />);
  expect(screen.getByText("Кроссовки")).toBeInTheDocument();
  expect(screen.getByText("5000.00")).toBeInTheDocument();
  expect(screen.getByText("—")).toBeInTheDocument(); // цена "Без цены"
});

it("does nothing when the delete confirmation is declined", async () => {
  render(<ProductsTable botId="1" apiBaseUrl="http://api" products={products} pageSize={10} />);

  fireEvent.click(screen.getAllByRole("button", { name: /удалить/i })[0]);
  fireEvent.click(screen.getByRole("button", { name: /отмена/i }));

  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  expect(api.deleteProduct).not.toHaveBeenCalled();
  expect(screen.getByText("Кроссовки")).toBeInTheDocument();
});

it("deletes the product and removes its row after confirming in the dialog", async () => {
  vi.mocked(api.deleteProduct).mockResolvedValue(undefined);
  render(<ProductsTable botId="1" apiBaseUrl="http://api" products={products} pageSize={10} />);

  // Сортировка по умолчанию (по названию) может поставить карточки в любом
  // порядке — находим кнопку удаления именно у "Кроссовки", а не по индексу.
  const card = screen.getByText("Кроссовки").closest("div")!;
  fireEvent.click(within(card).getByRole("button", { name: /удалить/i }));
  const dialog = screen.getByRole("alertdialog");
  expect(within(dialog).getByText(/удалить товар/i)).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole("button", { name: /удалить/i }));

  await waitFor(() => {
    expect(api.deleteProduct).toHaveBeenCalledWith("http://api", "1", "p1");
  });
  await waitFor(() => {
    expect(screen.queryByText("Кроссовки")).not.toBeInTheDocument();
  });
  expect(refreshMock).toHaveBeenCalled();
  expect(screen.getByRole("status")).toHaveTextContent(/товар удалён/i);
});

it("shows an error and keeps the row when deletion fails", async () => {
  vi.mocked(api.deleteProduct).mockRejectedValue(new Error("delete failed"));
  render(<ProductsTable botId="1" apiBaseUrl="http://api" products={products} pageSize={10} />);

  fireEvent.click(screen.getAllByRole("button", { name: /удалить/i })[0]);
  fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: /удалить/i }));

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
    media: [],
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

it("renders a thumbnail for the first media item and nothing for a product without media", () => {
  render(<ProductsTable botId="1" apiBaseUrl="http://api" products={products} pageSize={10} />);

  const thumbnail = screen.getByRole("img", { name: /кроссовки/i });
  expect(thumbnail).toHaveAttribute("src", "http://api/bots/1/products/p1/media/ph1");
  expect(screen.queryByRole("img", { name: /без цены/i })).not.toBeInTheDocument();
});

it("renders a <video> thumbnail when the first media item is a video", () => {
  const withVideoFirst: Product[] = [
    {
      ...products[0],
      media: [{ id: "vid1", position: 0, mime_type: "video/mp4" }],
    },
  ];
  render(
    <ProductsTable botId="1" apiBaseUrl="http://api" products={withVideoFirst} pageSize={10} />,
  );

  expect(screen.queryByRole("img", { name: /кроссовки/i })).not.toBeInTheDocument();
  const video = document.querySelector("video");
  expect(video).not.toBeNull();
  expect(video).toHaveAttribute("src", "http://api/bots/1/products/p1/media/vid1");
});

it("shows an empty state when there are no products", () => {
  render(<ProductsTable botId="1" apiBaseUrl="http://api" products={[]} pageSize={10} />);
  expect(screen.getByText("Товаров пока нет")).toBeInTheDocument();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});

it("defaults to the cards view", () => {
  render(<ProductsTable botId="1" apiBaseUrl="http://api" products={products} pageSize={10} />);
  expect(screen.getByRole("button", { name: "Карточки" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});

it("switches to the table view and back", () => {
  render(<ProductsTable botId="1" apiBaseUrl="http://api" products={products} pageSize={10} />);

  fireEvent.click(screen.getByRole("button", { name: "Список" }));
  expect(screen.getByRole("table")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Карточки" }));
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});

it("filters by name via the search input", () => {
  render(<ProductsTable botId="1" apiBaseUrl="http://api" products={products} pageSize={10} />);

  fireEvent.change(screen.getByLabelText("Поиск товаров"), { target: { value: "кросс" } });

  expect(screen.getByText("Кроссовки")).toBeInTheDocument();
  expect(screen.queryByText("Без цены")).not.toBeInTheDocument();
});

it("shows 'ничего не найдено' when the search matches nothing", () => {
  render(<ProductsTable botId="1" apiBaseUrl="http://api" products={products} pageSize={10} />);

  fireEvent.change(screen.getByLabelText("Поиск товаров"), { target: { value: "нет такого" } });

  expect(screen.getByText("Ничего не найдено")).toBeInTheDocument();
});

it("sorts by price when the Цена header is clicked (table view)", () => {
  const withPrices: Product[] = [
    { ...products[0], id: "p1", name: "Дорогой", price: "9000.00" },
    { ...products[0], id: "p2", name: "Дешёвый", price: "1000.00" },
  ];
  render(<ProductsTable botId="1" apiBaseUrl="http://api" products={withPrices} pageSize={10} />);
  fireEvent.click(screen.getByRole("button", { name: "Список" }));

  fireEvent.click(screen.getByRole("button", { name: /цена/i }));
  let cells = screen.getAllByRole("row").slice(1).map((row) => row.textContent);
  expect(cells[0]).toContain("Дешёвый");

  // Второй клик по тому же заголовку — разворот направления.
  fireEvent.click(screen.getByRole("button", { name: /цена/i }));
  cells = screen.getAllByRole("row").slice(1).map((row) => row.textContent);
  expect(cells[0]).toContain("Дорогой");
});
