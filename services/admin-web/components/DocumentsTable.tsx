"use client";

import { useMemo, useState } from "react";
import { deleteDocument, uploadDocument, type BotDocument } from "@/lib/api";
import { useToast } from "@/components/ToastProvider";
import { formatBishkekDateTime } from "@/lib/formatDate";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { SortableTh, type SortDirection } from "@/components/ui/SortableTh";
import { Table } from "@/components/ui/Table";

interface DocumentsTableProps {
  botId: string;
  apiBaseUrl: string;
  documents: BotDocument[];
}

type SortKey = "filename" | "mime_type" | "created_at";

export function DocumentsTable({ botId, apiBaseUrl, documents }: DocumentsTableProps) {
  const { showError, showSuccess } = useToast();
  const [rows, setRows] = useState(documents);
  const [uploading, setUploading] = useState(false);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("created_at");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");

  const visibleRows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = q === "" ? rows : rows.filter((doc) => doc.filename.toLowerCase().includes(q));
    const sorted = [...filtered].sort((a, b) => {
      const cmp = a[sortKey].localeCompare(b[sortKey], "ru");
      return sortDirection === "asc" ? cmp : -cmp;
    });
    return sorted;
  }, [rows, query, sortKey, sortDirection]);

  function toggleSort(key: SortKey): void {
    if (key === sortKey) {
      setSortDirection((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDirection("asc");
    }
  }

  const handleUpload = async (files: FileList | null) => {
    const file = files?.[0];
    if (!file) {
      return;
    }
    setUploading(true);
    try {
      const uploaded = await uploadDocument(apiBaseUrl, botId, file);
      setRows((current) => [uploaded, ...current]);
      showSuccess("Файл загружен");
    } catch (err) {
      showError(err instanceof Error ? err.message : "Не удалось загрузить файл");
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (documentId: string) => {
    try {
      await deleteDocument(apiBaseUrl, botId, documentId);
      setRows((current) => current.filter((row) => row.id !== documentId));
      showSuccess("Файл удалён");
    } catch (err) {
      showError(err instanceof Error ? err.message : "Не удалось удалить");
    }
  };

  return (
    <div className="space-y-5">
      <Card className="p-5">
        <label className="mb-0 block text-sm font-medium text-ink">
          Загрузить файл
          <input
            type="file"
            disabled={uploading}
            onChange={(e) => void handleUpload(e.target.files)}
            aria-label="Файл документа"
            className="mt-1.5 block text-sm text-ink-soft file:mr-3 file:rounded-lg file:border-0 file:bg-accent file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-white hover:file:bg-accent-hover disabled:opacity-60"
          />
        </label>
        {uploading && <p className="mt-2 text-xs text-ink-soft">Загружаем…</p>}
      </Card>

      {rows.length === 0 ? (
        <EmptyState
          title="Документов пока нет"
          description="Загруженные файлы бот сможет отправлять клиентам по запросу."
        />
      ) : (
        <>
          <Input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Поиск по имени файла…"
            aria-label="Поиск документов"
            className="max-w-sm"
          />
          {visibleRows.length === 0 ? (
            <EmptyState title="Ничего не найдено" description="Попробуйте другой запрос." />
          ) : (
            <Table>
              <table>
                <thead>
                  <tr>
                    <SortableTh
                      label="Имя файла"
                      active={sortKey === "filename"}
                      direction={sortDirection}
                      onClick={() => toggleSort("filename")}
                    />
                    <SortableTh
                      label="Тип"
                      active={sortKey === "mime_type"}
                      direction={sortDirection}
                      onClick={() => toggleSort("mime_type")}
                    />
                    <SortableTh
                      label="Загружен"
                      active={sortKey === "created_at"}
                      direction={sortDirection}
                      onClick={() => toggleSort("created_at")}
                    />
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {visibleRows.map((doc) => (
                    <tr key={doc.id}>
                      <td>{doc.filename}</td>
                      <td className="font-mono">{doc.mime_type}</td>
                      <td className="text-ink-soft">{formatBishkekDateTime(doc.created_at)}</td>
                      <td>
                        <Button variant="danger" onClick={() => setPendingDeleteId(doc.id)}>
                          Удалить
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Table>
          )}
        </>
      )}

      <ConfirmDialog
        open={pendingDeleteId !== null}
        title="Удалить файл?"
        description="Это действие необратимо — бот больше не сможет отправлять этот файл."
        onConfirm={() => {
          const id = pendingDeleteId;
          setPendingDeleteId(null);
          if (id) void handleDelete(id);
        }}
        onCancel={() => setPendingDeleteId(null)}
      />
    </div>
  );
}
