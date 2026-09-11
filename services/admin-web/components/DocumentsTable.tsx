"use client";

import { useState } from "react";
import { deleteDocument, uploadDocument, type BotDocument } from "@/lib/api";
import { useToast } from "@/components/ToastProvider";

interface DocumentsTableProps {
  botId: string;
  apiBaseUrl: string;
  documents: BotDocument[];
}

export function DocumentsTable({ botId, apiBaseUrl, documents }: DocumentsTableProps) {
  const { showError, showSuccess } = useToast();
  const [rows, setRows] = useState(documents);
  const [uploading, setUploading] = useState(false);

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
    <>
      <label>
        Загрузить файл
        <input
          type="file"
          disabled={uploading}
          onChange={(e) => void handleUpload(e.target.files)}
          aria-label="Файл документа"
        />
      </label>
      {uploading && <p>Загружаем…</p>}
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
              <td>{doc.mime_type}</td>
              <td>
                <button onClick={() => void handleDelete(doc.id)}>Удалить</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
