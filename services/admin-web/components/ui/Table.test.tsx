import { expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Table } from "@/components/ui/Table";

it("renders the wrapped table structure unchanged", () => {
  render(
    <Table>
      <table>
        <thead>
          <tr>
            <th>Имя</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Кофейня</td>
          </tr>
        </tbody>
      </table>
    </Table>,
  );
  expect(screen.getByRole("table")).toBeInTheDocument();
  expect(screen.getByRole("columnheader", { name: "Имя" })).toBeInTheDocument();
  expect(screen.getByRole("cell", { name: "Кофейня" })).toBeInTheDocument();
});
