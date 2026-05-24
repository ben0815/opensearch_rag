import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Badge, Button, Modal, ProgressBar, Spinner, Table } from "react-bootstrap";
import { useTranslation } from "react-i18next";
import { documents as docsApi } from "@/api/client";
import { ApiError } from "@/api/client";
import { useInstanceStore } from "@/stores/instanceStore";
import { useAuthStore } from "@/stores/authStore";
import { useDocumentUpload } from "@/hooks/useDocumentUpload";
import type { DocumentOut } from "@/types/api";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export default function DocumentsPage() {
  const { t } = useTranslation();
  const selectedInstance = useInstanceStore((s) => s.selectedInstance());
  const user = useAuthStore((s) => s.user);

  const [docs, setDocs] = useState<DocumentOut[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deletingHash, setDeletingHash] = useState<string | null>(null);
  const [showUpload, setShowUpload] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const canManage =
    user?.is_global_admin || selectedInstance?.role === "manager";

  const { files: uploadFiles, uploading, upload, reset: resetUpload } = useDocumentUpload(
    selectedInstance?.id ?? 0,
  );

  const loadDocs = useCallback(async () => {
    if (!selectedInstance) return;
    setLoading(true);
    setError(null);
    try {
      const data = await docsApi.list(selectedInstance.id);
      setDocs(data);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("errors.serverError"));
    } finally {
      setLoading(false);
    }
  }, [selectedInstance, t]);

  useEffect(() => {
    void loadDocs();
  }, [loadDocs]);

  async function handleDelete(hash: string) {
    if (!selectedInstance) return;
    setDeletingHash(hash);
    try {
      await docsApi.delete(selectedInstance.id, hash);
      setDocs((prev) => prev.filter((d) => d.sha256 !== hash));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("errors.serverError"));
    } finally {
      setDeletingHash(null);
    }
  }

  function handleFilePick(files: FileList | null) {
    if (!files) return;
    void upload(Array.from(files));
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    handleFilePick(e.dataTransfer.files);
  }

  function handleUploadClose() {
    setShowUpload(false);
    resetUpload();
    void loadDocs();
  }

  if (!selectedInstance) {
    return (
      <div className="d-flex h-100 align-items-center justify-content-center text-body-secondary">
        <p>{t("chat.selectInstance")}</p>
      </div>
    );
  }

  return (
    <div className="p-4">
      <div className="d-flex align-items-center justify-content-between mb-4">
        <h4 className="mb-0">
          <i className="bi bi-file-earmark-text me-2" />
          {selectedInstance.name} — {t("documents.title")}
        </h4>
        <div className="d-flex gap-2">
          <Button variant="outline-secondary" size="sm" onClick={loadDocs} disabled={loading}>
            <i className="bi bi-arrow-clockwise" />
          </Button>
          {canManage && (
            <Button size="sm" onClick={() => setShowUpload(true)}>
              <i className="bi bi-upload me-1" />
              {t("documents.upload")}
            </Button>
          )}
        </div>
      </div>

      {error && (
        <Alert variant="danger" dismissible onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {loading ? (
        <div className="text-center py-5">
          <Spinner animation="border" variant="primary" />
        </div>
      ) : docs.length === 0 ? (
        <div className="text-center py-5 text-body-secondary">
          <i className="bi bi-inbox fs-1 d-block mb-3" />
          {t("documents.noDocuments")}
        </div>
      ) : (
        <Table responsive hover>
          <thead>
            <tr>
              <th>{t("common.name")}</th>
              <th>Seiten</th>
              <th>Chunks</th>
              <th>Größe</th>
              <th>Indiziert</th>
              {canManage && <th />}
            </tr>
          </thead>
          <tbody>
            {docs.map((doc) => (
              <tr key={doc.sha256}>
                <td>
                  <i className="bi bi-file-earmark-pdf text-danger me-2" />
                  {doc.title}
                </td>
                <td>{doc.page_count}</td>
                <td>{doc.chunk_count}</td>
                <td>{formatBytes(doc.file_size)}</td>
                <td className="text-nowrap small text-body-secondary">
                  {new Date(doc.indexed_date).toLocaleDateString()}
                </td>
                {canManage && (
                  <td className="text-end">
                    <Button
                      variant="outline-danger"
                      size="sm"
                      disabled={deletingHash === doc.sha256}
                      onClick={() => {
                        if (confirm(t("documents.deleteConfirm")))
                          void handleDelete(doc.sha256);
                      }}
                    >
                      {deletingHash === doc.sha256 ? (
                        <Spinner animation="border" size="sm" />
                      ) : (
                        <i className="bi bi-trash" />
                      )}
                    </Button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </Table>
      )}

      {/* Upload Modal */}
      <Modal show={showUpload} onHide={handleUploadClose} size="lg">
        <Modal.Header closeButton>
          <Modal.Title>{t("documents.upload")}</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          {uploadFiles.length === 0 ? (
            <div
              className={`drop-zone text-center p-5 ${dragOver ? "dragover" : ""}`}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
            >
              <i className="bi bi-cloud-upload fs-1 text-body-secondary d-block mb-2" />
              <p className="mb-1">{t("documents.uploadDrop")}</p>
              <small className="text-body-secondary">PDF, DOCX, TXT …</small>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept=".pdf,.docx,.txt"
                className="d-none"
                onChange={(e) => handleFilePick(e.target.files)}
              />
            </div>
          ) : (
            <div className="d-flex flex-column gap-3">
              {uploadFiles.map((fs) => (
                <div key={fs.file.name}>
                  <div className="d-flex justify-content-between mb-1">
                    <span className="small text-truncate">{fs.file.name}</span>
                    <Badge
                      bg={
                        fs.status === "ok" ? "success"
                          : fs.status === "error" ? "danger"
                          : fs.status === "already_indexed" ? "secondary"
                          : "primary"
                      }
                    >
                      {fs.status === "already_indexed"
                        ? t("documents.alreadyIndexed")
                        : fs.status}
                    </Badge>
                  </div>
                  <ProgressBar
                    now={fs.progress}
                    variant={fs.status === "error" ? "danger" : "primary"}
                    animated={fs.status === "uploading"}
                  />
                  {fs.error && <small className="text-danger">{fs.error}</small>}
                </div>
              ))}
            </div>
          )}
        </Modal.Body>
        <Modal.Footer>
          <Button variant="secondary" onClick={handleUploadClose} disabled={uploading}>
            {uploading ? t("documents.uploading") : t("common.close")}
          </Button>
        </Modal.Footer>
      </Modal>
    </div>
  );
}
