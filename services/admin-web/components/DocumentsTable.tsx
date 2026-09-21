"use client";

import { useState } from "react";
import { deleteDocument, uploadDocument, type BotDocument } from "@/lib/api";
import { useToast } from "@/components/ToastProvider";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { Table } from "@/components/ui/Table";

interface DocumentsTableProps {
  botId: string;
  apiBaseUrl: string;
  documents: BotDocument[];
}

export function DocumentsTable({ botId, apiBaseUrl, documents }: DocumentsTableProps) {
  const { showError, showSuccess } = useToast();
  const [rows, setRows] = useState(documents);
  const [uploading, setUploading] = useState(false);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);

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
        <Table>
          <table>
            <thead>
              <tr>
                <th>Имя файла</th>
                <th>Тип</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((doc) => (
                <tr key={doc.id}>
                  <td>{doc.filename}</td>
                  <td className="font-mono">{doc.mime_type}</td>
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
