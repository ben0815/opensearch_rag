import { useCallback, useState } from "react";
import type { UploadProgressEvent } from "@/types/api";

export interface FileUploadMeta {
  display_name?: string;
  description?: string;
  sheets?: string[] | null;
  existing_hash?: string;
  valid_until?: string;
}

export interface UploadFileState {
  file: File;
  progress: number;
  status: "pending" | "uploading" | "ok" | "already_indexed" | "error";
  error?: string;
  chunk_count?: number;
  warnings?: string[];
}

export function useDocumentUpload(instanceId: number) {
  const [files, setFiles] = useState<UploadFileState[]>([]);
  const [uploading, setUploading] = useState(false);

  function getCsrf(): string {
    const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  const upload = useCallback(
    async (selectedFiles: File[], metaList: FileUploadMeta[] = []) => {
      if (!selectedFiles.length || uploading) return;

      const initial: UploadFileState[] = selectedFiles.map((f) => ({
        file: f,
        progress: 0,
        status: "pending",
      }));
      setFiles(initial);
      setUploading(true);

      const formData = new FormData();
      for (const f of selectedFiles) formData.append("files", f);

      // Metadaten positionell zu files[] abgestimmt
      const metadata = selectedFiles.map((_, i) => ({
        display_name: metaList[i]?.display_name ?? "",
        description: metaList[i]?.description ?? "",
        sheets: metaList[i]?.sheets ?? null,
        existing_hash: metaList[i]?.existing_hash ?? "",
        valid_until: metaList[i]?.valid_until ?? "",
      }));
      formData.append("metadata", JSON.stringify(metadata));

      try {
        const resp = await fetch(`/api/documents/${instanceId}/upload`, {
          method: "POST",
          headers: { "X-CSRF-Token": getCsrf() },
          credentials: "include",
          body: formData,
        });

        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

        const reader = resp.body!.getReader();
        const decoder = new TextDecoder();
        let buf = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });

          const lines = buf.split("\n");
          buf = lines.pop() ?? "";

          for (const line of lines) {
            if (!line.startsWith("data:")) continue;
            try {
              const event = JSON.parse(line.slice(5).trim()) as UploadProgressEvent;

              if ("done" in event) continue;

              setFiles((prev) =>
                prev.map((fs) => {
                  if (fs.file.name !== event.file) return fs;
                  if ("status" in event) {
                    if (event.status === "ok") {
                      return {
                        ...fs,
                        progress: 100,
                        status: "ok" as const,
                        chunk_count: event.chunk_count,
                        warnings: event.warnings,
                      };
                    }
                    return {
                      ...fs,
                      progress: 100,
                      status: event.status === "error" ? "error" : event.status,
                      error: event.status === "error" ? event.error : undefined,
                    };
                  }
                  return { ...fs, progress: event.progress, status: "uploading" };
                }),
              );
            } catch {
              /* ignore parse errors */
            }
          }
        }
      } catch (err) {
        setFiles((prev) =>
          prev.map((fs) => ({ ...fs, status: "error", error: String(err) })),
        );
      } finally {
        setUploading(false);
      }
    },
    [instanceId, uploading],
  );

  const reset = useCallback(() => setFiles([]), []);

  return { files, uploading, upload, reset };
}
