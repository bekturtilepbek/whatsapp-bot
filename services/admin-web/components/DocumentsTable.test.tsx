import { afterEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { DocumentsTable } from "@/components/DocumentsTable";
import * as api from "@/lib/api";
import type { BotDocument } from "@/lib/api";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    uploadDocument: vi.fn(),
    deleteDocument: vi.fn(),
  };
});

const documents: BotDocument[] = [
  { id: "d1", filename: "price.pdf", mime_type: "application/pdf", created_at: "2026-09-11T10:00:00Z" },
  { id: "d2", filename: "catalog.docx", mime_type: "application/msword", created_at: "2026-09-11T10:00:00Z" },
];

function makeFile(name: string, content = "fake bytes", type = "application/pdf"): File {
  return new File([content], name, { type });
}

afterEach(() => {
  vi.clearAllMocks();
});

it("renders each document's filename and mime type", () => {
  render(<DocumentsTable botId="1" apiBaseUrl="http://api" documents={documents} />);
  expect(screen.getByText("price.pdf")).toBeInTheDocument();
  expect(screen.getByText("application/pdf")).toBeInTheDocument();
  expect(screen.getByText("catalog.docx")).toBeInTheDocument();
});

it("uploads a selected file and prepends it to the list", async () => {
  const uploaded: BotDocument = {
    id: "d3",
    filename: "new.pdf",
    mime_type: "application/pdf",
    created_at: "2026-09-11T10:00:00Z",
  };
  vi.mocked(api.uploadDocument).mockResolvedValue(uploaded);
  render(<DocumentsTable botId="1" apiBaseUrl="http://api" documents={documents} />);

  const file = makeFile("new.pdf");
  fireEvent.change(screen.getByLabelText("Файл документа"), { target: { files: [file] } });

  await waitFor(() => {
    expect(api.uploadDocument).toHaveBeenCalledWith("http://api", "1", file);
  });
  expect(await screen.findByText("new.pdf")).toBeInTheDocument();
});

it("shows an error when upload fails", async () => {
  vi.mocked(api.uploadDocument).mockRejectedValue(new Error("upload failed: 409"));
  render(<DocumentsTable botId="1" apiBaseUrl="http://api" documents={documents} />);

  fireEvent.change(screen.getByLabelText("Файл документа"), {
    target: { files: [makeFile("dup.pdf")] },
  });

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent(/upload failed: 409/i);
  });
});

it("does nothing when the file input is cleared without a selection", async () => {
  render(<DocumentsTable botId="1" apiBaseUrl="http://api" documents={documents} />);
  fireEvent.change(screen.getByLabelText("Файл документа"), { target: { files: [] } });
  await waitFor(() => {
    expect(api.uploadDocument).not.toHaveBeenCalled();
  });
});

it("deletes a document and removes its row", async () => {
  vi.mocked(api.deleteDocument).mockResolvedValue(undefined);
  render(<DocumentsTable botId="1" apiBaseUrl="http://api" documents={documents} />);

  fireEvent.click(screen.getAllByRole("button", { name: /удалить/i })[0]);

  await waitFor(() => {
    expect(api.deleteDocument).toHaveBeenCalledWith("http://api", "1", "d1");
  });
  await waitFor(() => {
    expect(screen.queryByText("price.pdf")).not.toBeInTheDocument();
  });
});

it("shows an error and keeps the row when deletion fails", async () => {
  vi.mocked(api.deleteDocument).mockRejectedValue(new Error("delete failed"));
  render(<DocumentsTable botId="1" apiBaseUrl="http://api" documents={documents} />);

  fireEvent.click(screen.getAllByRole("button", { name: /удалить/i })[0]);

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent(/delete failed/i);
  });
  expect(screen.getByText("price.pdf")).toBeInTheDocument();
});
