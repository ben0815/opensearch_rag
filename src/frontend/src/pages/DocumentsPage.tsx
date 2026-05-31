import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Alert, Badge, Button, Form, Modal, ProgressBar, Spinner, Table } from "react-bootstrap";
import { useTranslation } from "react-i18next";
import { documents as docsApi } from "@/api/client";
import { ApiError } from "@/api/client";
import { useInstanceStore } from "@/stores/instanceStore";
import { useAuthStore } from "@/stores/authStore";
import { useDocumentUpload, type FileUploadMeta } from "@/hooks/useDocumentUpload";
import type { DocumentOut } from "@/types/api";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function cleanFilename(name: string): string {
  return name
    .replace(/\.[^/.]+$/, "")
    .replace(/[_-]+/g, " ")
    .replace(/\s*(v\d+|final|neu|kopie|copy)\s*/gi, " ")
    .trim();
}

function isExpired(validUntil: string): boolean {
  return new Date(validUntil) < new Date();
}

function isExpiringSoon(validUntil: string): boolean {
  return !isExpired(validUntil) && new Date(validUntil).getTime() - Date.now() < 30 * 24 * 60 * 60 * 1000;
}

function fileIcon(name: string): string {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  if (ext === "pdf") return "bi-file-earmark-pdf text-danger";
  if (ext === "docx") return "bi-file-earmark-word text-primary";
  if (ext === "xlsx") return "bi-file-earmark-excel text-success";
  if (ext === "csv") return "bi-file-earmark-spreadsheet text-success";
  return "bi-file-earmark-text text-secondary";
}

export default function DocumentsPage() {
  const { t } = useTranslation();
  const selectedInstance = useInstanceStore((s) => s.selectedInstance());
  const user = useAuthStore((s) => s.user);

  const [docs, setDocs] = useState<DocumentOut[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  type SortKey = keyof Pick<DocumentOut, "title" | "page_count" | "chunk_count" | "file_size" | "indexed_date">;
  const [sortKey, setSortKey] = useState<SortKey>("indexed_date");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [deletingHash, setDeletingHash] = useState<string | null>(null);
  const [showUpload, setShowUpload] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Upload-Metadaten-State (Phase 3)
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [metaList, setMetaList] = useState<FileUploadMeta[]>([]);

  const canManage =
    user?.is_global_admin || selectedInstance?.role === "manager";

  function handleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  function sortIcon(key: SortKey) {
    if (key !== sortKey) return <i className="bi bi-arrow-down-up ms-1 text-body-tertiary" />;
    return sortDir === "asc"
      ? <i className="bi bi-arrow-up ms-1" />
      : <i className="bi bi-arrow-down ms-1" />;
  }

  const sortedDocs = useMemo(() => {
    return [...docs].sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      const cmp = typeof av === "string" ? av.localeCompare(bv as string) : (av as number) - (bv as number);
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [docs, sortKey, sortDir]);

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
    const arr = Array.from(files);
    setPendingFiles(arr);
    setMetaList(arr.map((f) => ({
      display_name: cleanFilename(f.name),
      description: "",
      sheets: null,
      existing_hash: "",
    })));
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    handleFilePick(e.dataTransfer.files);
  }

  async function handleUpload() {
    if (!pendingFiles.length || !selectedInstance) return;

    const names = metaList.map((m, i) =>
      (m.display_name?.trim() || cleanFilename(pendingFiles[i].name))
    );

    let resolvedMeta = metaList;
    try {
      const { conflicts } = await docsApi.check(selectedInstance.id, names);
      if (conflicts.length > 0) {
        const conflictNames = conflicts.map((c) => `"${c.name}"`).join(", ");
        if (!confirm(t("documents.replace.message", { names: conflictNames }))) return;
        // Existing-Hash setzen damit Backend nach erfolgreichem Upload löscht
        resolvedMeta = metaList.map((m, i) => {
          const conflict = conflicts.find((c) => c.name === names[i]);
          return conflict ? { ...m, existing_hash: conflict.hash } : m;
        });
        setMetaList(resolvedMeta);
      }
    } catch {
      // /check-Fehler: Upload trotzdem starten
    }

    void upload(pendingFiles, resolvedMeta);
    setPendingFiles([]);
  }

  function handleUploadClose() {
    setShowUpload(false);
    resetUpload();
    setPendingFiles([]);
    setMetaList([]);
    void loadDocs();
  }

  function updateMeta(idx: number, patch: Partial<FileUploadMeta>) {
    setMetaList((prev) => prev.map((m, i) => (i === idx ? { ...m, ...patch } : m)));
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
              <th style={{ cursor: "pointer" }} onClick={() => handleSort("title")}>
                {t("common.name")}{sortIcon("title")}
              </th>
              <th style={{ cursor: "pointer" }} onClick={() => handleSort("page_count")}>
                Seiten{sortIcon("page_count")}
              </th>
              <th style={{ cursor: "pointer" }} onClick={() => handleSort("chunk_count")}>
                Chunks{sortIcon("chunk_count")}
              </th>
              <th style={{ cursor: "pointer" }} onClick={() => handleSort("file_size")}>
                Größe{sortIcon("file_size")}
              </th>
              <th style={{ cursor: "pointer" }} onClick={() => handleSort("indexed_date")}>
                Indiziert{sortIcon("indexed_date")}
              </th>
              {canManage && <th />}
            </tr>
          </thead>
          <tbody>
            {sortedDocs.map((doc) => (
              <tr key={doc.sha256}>
                <td>
                  <i className={`bi ${fileIcon(doc.title)} me-2`} />
                  {doc.display_name || doc.title}
                  {doc.display_name && doc.display_name !== doc.title && (
                    <small className="text-body-secondary ms-2">({doc.title})</small>
                  )}
                  {doc.valid_until && (
                    <div className="mt-1">
                      <Badge
                        bg={isExpired(doc.valid_until) ? "danger" : isExpiringSoon(doc.valid_until) ? "warning" : "secondary"}
                        text={isExpiringSoon(doc.valid_until) ? "dark" : undefined}
                        className="small"
                      >
                        {isExpired(doc.valid_until)
                          ? t("documents.validUntil.expired")
                          : isExpiringSoon(doc.valid_until)
                          ? `${t("documents.validUntil.expiresSoon")}: ${doc.valid_until}`
                          : `${t("documents.validUntil.label")}: ${doc.valid_until}`}
                      </Badge>
                    </div>
                  )}
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

          {/* Zustand 1: Drop-Zone (keine Dateien ausgewählt, nicht am Hochladen) */}
          {pendingFiles.length === 0 && uploadFiles.length === 0 && (
            <div
              className={`drop-zone text-center p-5 ${dragOver ? "dragover" : ""}`}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
            >
              <i className="bi bi-cloud-upload fs-1 text-body-secondary d-block mb-2" />
              <p className="mb-1">{t("documents.uploadDrop")}</p>
              <small className="text-body-secondary">PDF, DOCX, XLSX, CSV, TXT, MD</small>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept=".pdf,.docx,.txt,.xlsx,.csv,.md,application/pdf,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/csv,text/markdown"
                className="d-none"
                onChange={(e) => handleFilePick(e.target.files)}
              />
            </div>
          )}

          {/* Zustand 2: Metadaten-Eingabe (Dateien ausgewählt, noch nicht hochgeladen) */}
          {pendingFiles.length > 0 && !uploading && uploadFiles.length === 0 && (
            <div className="d-flex flex-column gap-3">
              {pendingFiles.map((file, idx) => {
                const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
                const isTabular = ext === "xlsx" || ext === "csv";
                const isDocx = ext === "docx";
                const meta = metaList[idx] ?? {};
                const missingDesc = isTabular && !meta.description?.trim();

                return (
                  <div key={file.name} className="border rounded p-3">
                    <div className="d-flex align-items-center gap-2 mb-2">
                      <i className={`bi ${fileIcon(file.name)} fs-5`} />
                      <span className="fw-semibold text-truncate">{file.name}</span>
                      <Badge bg="secondary" className="ms-auto text-nowrap">
                        {formatBytes(file.size)}
                      </Badge>
                    </div>

                    {isDocx && (
                      <Alert variant="info" className="py-1 px-2 mb-2 small">
                        <i className="bi bi-info-circle me-1" />
                        {t("documents.docx.textFieldsHint")}
                      </Alert>
                    )}

                    <Form.Group className="mb-2">
                      <Form.Label className="small mb-1">{t("documents.displayName.label")}</Form.Label>
                      <Form.Control
                        size="sm"
                        type="text"
                        maxLength={255}
                        placeholder={t("documents.displayName.placeholder")}
                        value={meta.display_name ?? ""}
                        onChange={(e) => updateMeta(idx, { display_name: e.target.value })}
                      />
                    </Form.Group>

                    {isTabular && (
                      <Form.Group className="mb-2">
                        <Form.Label className="small mb-1">
                          {t("documents.description.placeholder")}
                          <span className="text-body-secondary ms-1">
                            ({(meta.description ?? "").length}/500)
                          </span>
                        </Form.Label>
                        <Form.Control
                          as="textarea"
                          size="sm"
                          rows={2}
                          maxLength={500}
                          placeholder={t("documents.description.placeholder")}
                          value={meta.description ?? ""}
                          onChange={(e) => updateMeta(idx, { description: e.target.value })}
                        />
                        <Form.Text className="text-body-secondary">
                          {t("documents.description.hint")}
                        </Form.Text>
                      </Form.Group>
                    )}

                    {ext === "xlsx" && (
                      <Form.Group className="mb-0">
                        <Form.Label className="small mb-1">{t("documents.sheets.label")}</Form.Label>
                        <Form.Control
                          size="sm"
                          type="text"
                          placeholder={t("documents.sheets.placeholder")}
                          value={meta.sheets?.join(",") ?? ""}
                          onChange={(e) => {
                            const val = e.target.value.trim();
                            updateMeta(idx, {
                              sheets: val ? val.split(",").map((s) => s.trim()).filter(Boolean) : null,
                            });
                          }}
                        />
                      </Form.Group>
                    )}

                    <Form.Group className="mb-0 mt-2">
                      <Form.Label className="small mb-1">{t("documents.validUntil.label")}</Form.Label>
                      <Form.Control
                        size="sm"
                        type="date"
                        value={meta.valid_until ?? ""}
                        onChange={(e) => updateMeta(idx, { valid_until: e.target.value || undefined })}
                      />
                      <Form.Text className="text-body-secondary">
                        {t("documents.validUntil.hint")}
                      </Form.Text>
                    </Form.Group>

                    {missingDesc && (
                      <Alert variant="warning" className="py-1 px-2 mt-2 mb-0 small">
                        <i className="bi bi-exclamation-triangle me-1" />
                        {t("documents.qualityIndicator.missingDescription")}
                      </Alert>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {/* Zustand 3: Fortschritt & Ergebnisse */}
          {(uploading || uploadFiles.length > 0) && (
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
                        : fs.status === "ok"
                        ? `✓ ${fs.chunk_count ?? ""} Chunks`
                        : fs.status}
                    </Badge>
                  </div>
                  <ProgressBar
                    now={fs.progress}
                    variant={fs.status === "error" ? "danger" : "primary"}
                    animated={fs.status === "uploading" || fs.status === "pending"}
                  />
                  {fs.error && <small className="text-danger">{fs.error}</small>}
                  {fs.warnings && fs.warnings.length > 0 && (
                    <Alert variant="warning" className="py-1 px-2 mt-1 mb-0 small">
                      {fs.warnings.map((w, wi) => (
                        <div key={wi}><i className="bi bi-exclamation-triangle me-1" />{w}</div>
                      ))}
                    </Alert>
                  )}
                </div>
              ))}
            </div>
          )}
        </Modal.Body>
        <Modal.Footer>
          {pendingFiles.length > 0 && !uploading && uploadFiles.length === 0 && (
            <Button variant="primary" onClick={() => void handleUpload()}>
              <i className="bi bi-upload me-1" />
              {t("documents.startUpload")}
            </Button>
          )}
          <Button variant="secondary" onClick={handleUploadClose} disabled={uploading}>
            {uploading ? t("documents.uploading") : t("common.close")}
          </Button>
        </Modal.Footer>
      </Modal>
    </div>
  );
}
