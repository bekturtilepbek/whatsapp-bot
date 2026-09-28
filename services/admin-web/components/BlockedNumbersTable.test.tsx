import { afterEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@/lib/test-utils";
import { BlockedNumbersTable } from "@/components/BlockedNumbersTable";
import * as api from "@/lib/api";
import type { BlockedNumber } from "@/lib/api";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    addBlockedNumber: vi.fn(),
    deleteBlockedNumber: vi.fn(),
    fetchBlockedNumbers: vi.fn(),
  };
});

const numbers: BlockedNumber[] = [{ phone: "996700000001" }, { phone: "996700000002" }];

afterEach(() => {
  vi.clearAllMocks();
});

it("renders each blocked number", () => {
  render(
    <BlockedNumbersTable botId="1" apiBaseUrl="http://api" numbers={numbers} pageSize={10} />,
  );
  expect(screen.getByText("996700000001")).toBeInTheDocument();
  expect(screen.getByText("996700000002")).toBeInTheDocument();
});

it("shows an error and does not call the api when the phone field is empty", async () => {
  render(
    <BlockedNumbersTable botId="1" apiBaseUrl="http://api" numbers={numbers} pageSize={10} />,
  );
  fireEvent.click(screen.getByRole("button", { name: /добавить/i }));

  expect(await screen.findByRole("alert")).toHaveTextContent(/введите номер телефона/i);
  expect(api.addBlockedNumber).not.toHaveBeenCalled();
  expect(screen.getByLabelText("Номер телефона")).toHaveAttribute("aria-invalid", "true");
  expect(screen.getByText("Номер телефона").closest("label")).toHaveClass("text-danger");
  const shakeWrapper = document.querySelector(".animate-shake");
  expect(shakeWrapper).toContainElement(screen.getByText("Номер телефона"));
  expect(shakeWrapper).toContainElement(screen.getByLabelText("Номер телефона"));
});

// Раньше "abc" уходил в API, становился "" и оставался в списке пустой
// строкой, которую нельзя удалить.
it.each(["abc", "123", "9999999999999999"])(
  "rejects %s before calling the api — not a phone number",
  async (value) => {
    render(
      <BlockedNumbersTable botId="1" apiBaseUrl="http://api" numbers={numbers} pageSize={10} />,
    );
    fireEvent.change(screen.getByLabelText("Номер телефона"), { target: { value } });
    fireEvent.click(screen.getByRole("button", { name: /добавить/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/от 7 до 15 цифр/i);
    expect(api.addBlockedNumber).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Номер телефона")).toHaveAttribute("aria-invalid", "true");
  },
);

it("adds a number and prepends it to the list", async () => {
  vi.mocked(api.addBlockedNumber).mockResolvedValue({ phone: "996700000003" });
  render(
    <BlockedNumbersTable botId="1" apiBaseUrl="http://api" numbers={numbers} pageSize={10} />,
  );

  fireEvent.change(screen.getByLabelText("Номер телефона"), {
    target: { value: "+996 700 00 00 03" },
  });
  fireEvent.click(screen.getByRole("button", { name: /добавить/i }));

  await waitFor(() => {
    expect(api.addBlockedNumber).toHaveBeenCalledWith("http://api", "1", "+996 700 00 00 03");
  });
  expect(await screen.findByText("996700000003")).toBeInTheDocument();
  expect((screen.getByLabelText("Номер телефона") as HTMLInputElement).value).toBe("");
  expect(screen.getByRole("status")).toHaveTextContent(/добавлен/i);
});

it("shows an error and does not clear the input when adding fails", async () => {
  vi.mocked(api.addBlockedNumber).mockRejectedValue(new Error("add failed"));
  render(
    <BlockedNumbersTable botId="1" apiBaseUrl="http://api" numbers={numbers} pageSize={10} />,
  );

  fireEvent.change(screen.getByLabelText("Номер телефона"), {
    target: { value: "996700000003" },
  });
  fireEvent.click(screen.getByRole("button", { name: /добавить/i }));

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent(/add failed/i);
  });
  expect((screen.getByLabelText("Номер телефона") as HTMLInputElement).value).toBe(
    "996700000003",
  );
});

it("deletes a number and removes its row", async () => {
  vi.mocked(api.deleteBlockedNumber).mockResolvedValue(undefined);
  render(
    <BlockedNumbersTable botId="1" apiBaseUrl="http://api" numbers={numbers} pageSize={10} />,
  );

  fireEvent.click(screen.getAllByRole("button", { name: /удалить/i })[0]);

  await waitFor(() => {
    expect(api.deleteBlockedNumber).toHaveBeenCalledWith("http://api", "1", "996700000001");
  });
  await waitFor(() => {
    expect(screen.queryByText("996700000001")).not.toBeInTheDocument();
  });
  expect(screen.getByRole("status")).toHaveTextContent(/удалён/i);
});

it("shows an error and keeps the row when deletion fails", async () => {
  vi.mocked(api.deleteBlockedNumber).mockRejectedValue(new Error("delete failed"));
  render(
    <BlockedNumbersTable botId="1" apiBaseUrl="http://api" numbers={numbers} pageSize={10} />,
  );

  fireEvent.click(screen.getAllByRole("button", { name: /удалить/i })[0]);

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent(/delete failed/i);
  });
  expect(screen.getByText("996700000001")).toBeInTheDocument();
});

it('hides "Показать ещё" when the first page is smaller than pageSize', () => {
  render(
    <BlockedNumbersTable botId="1" apiBaseUrl="http://api" numbers={numbers} pageSize={10} />,
  );
  expect(screen.queryByRole("button", { name: /показать ещё/i })).not.toBeInTheDocument();
});

it('shows "Показать ещё", loads and appends the next page, then hides once exhausted', async () => {
  render(
    <BlockedNumbersTable botId="1" apiBaseUrl="http://api" numbers={numbers} pageSize={2} />,
  );
  expect(screen.getByRole("button", { name: /показать ещё/i })).toBeInTheDocument();

  vi.mocked(api.fetchBlockedNumbers).mockResolvedValue([{ phone: "996700000003" }]);

  fireEvent.click(screen.getByRole("button", { name: /показать ещё/i }));

  await waitFor(() => {
    expect(api.fetchBlockedNumbers).toHaveBeenCalledWith("http://api", "1", {
      limit: 2,
      offset: 2,
    });
  });
  expect(await screen.findByText("996700000003")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /показать ещё/i })).not.toBeInTheDocument();
});

it('shows an error and keeps "Показать ещё" visible when loading more fails', async () => {
  render(
    <BlockedNumbersTable botId="1" apiBaseUrl="http://api" numbers={numbers} pageSize={2} />,
  );
  vi.mocked(api.fetchBlockedNumbers).mockRejectedValue(new Error("load more failed"));

  fireEvent.click(screen.getByRole("button", { name: /показать ещё/i }));

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent(/load more failed/i);
  });
  expect(screen.getByRole("button", { name: /показать ещё/i })).toBeInTheDocument();
});

it("shows an empty state when there are no blocked numbers", () => {
  render(<BlockedNumbersTable botId="1" apiBaseUrl="http://api" numbers={[]} pageSize={10} />);
  expect(screen.getByText("Чёрный список пуст")).toBeInTheDocument();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});

it("filters by phone via the search input", () => {
  render(<BlockedNumbersTable botId="1" apiBaseUrl="http://api" numbers={numbers} pageSize={10} />);

  fireEvent.change(screen.getByLabelText("Поиск по чёрному списку"), {
    target: { value: "0002" },
  });

  expect(screen.getByText("996700000002")).toBeInTheDocument();
  expect(screen.queryByText("996700000001")).not.toBeInTheDocument();
});

it("reverses sort order when the Номер header is clicked", () => {
  render(<BlockedNumbersTable botId="1" apiBaseUrl="http://api" numbers={numbers} pageSize={10} />);

  fireEvent.click(screen.getByRole("button", { name: /номер/i }));
  const cells = screen.getAllByRole("row").slice(1).map((row) => row.textContent);
  expect(cells[0]).toContain("996700000002");
});
