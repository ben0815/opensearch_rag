import { useCallback, useEffect, useState } from "react";
import { Alert, Badge, Button, Modal, Pagination, Spinner } from "react-bootstrap";
import { useTranslation } from "react-i18next";
import { marked } from "marked";
import DOMPurify from "dompurify";
import { chat as chatApi } from "@/api/client";
import { ApiError } from "@/api/client";
import { useInstanceStore } from "@/stores/instanceStore";
import type { ChatHistoryOut, PaginatedChatHistory } from "@/types/api";

const PER_PAGE = 20;

interface ContextDoc {
  filename: string;
  source: string;
  page?: number | null;
  score: number;
  excerpt: string;
}

function formatDuration(s: number): string {
  return s < 60 ? `${s.toFixed(1)} s` : `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`;
}

function DurationChip({ meta }: { meta: Record<string, unknown> | null }) {
  if (!meta) return null;
  const total = meta.duration_s != null ? Number(meta.duration_s) : null;
  const llm = meta.llm_generation_s != null ? Number(meta.llm_generation_s) : null;
  const secs = total ?? llm;
  if (secs == null) return null;
  return (
    <small className="text-body-secondary text-nowrap">
      <i className="bi bi-stopwatch me-1" />
      {formatDuration(secs)}
    </small>
  );
}

function SourcesSection({ docs }: { docs: ContextDoc[] }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);

  if (docs.length === 0) return (
    <div className="mt-3 pt-3 border-top small text-body-secondary">{t("history.noSources")}</div>
  );

  return (
    <div className="mt-3 pt-3 border-top">
      <Button
        variant="link"
        size="sm"
        className="p-0 text-decoration-none fw-semibold"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <i className={`bi bi-chevron-${open ? "up" : "down"} me-1`} />
        {t("history.sources")} ({docs.length})
      </Button>
      {open && (
        <div className="mt-2 d-flex flex-column gap-2">
          {docs.map((doc, i) => (
            <div key={i} className="p-2 rounded border small">
              <div className="d-flex justify-content-between align-items-center mb-1">
                <span className="fw-semibold text-truncate me-2">
                  <i className="bi bi-file-earmark-text me-1" />
                  {doc.filename}
                  {doc.page != null && (
                    <Badge bg="secondary-subtle" text="secondary" className="ms-2">
                      {t("chat.page", { page: doc.page })}
                    </Badge>
                  )}
                </span>
                <Badge bg="primary-subtle" text="primary" className="text-nowrap flex-shrink-0">
                  {t("chat.score", { score: doc.score.toFixed(3) })}
                </Badge>
              </div>
              <p className="mb-0 text-body-secondary" style={{ whiteSpace: "pre-wrap" }}>
                {doc.excerpt}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function TimingSection({ meta }: { meta: Record<string, unknown> | null }) {
  const { t } = useTranslation();
  if (!meta) return null;

  const retrieval = meta.retrieval_ms != null ? Number(meta.retrieval_ms) : null;
  const llm = meta.llm_generation_s != null ? Number(meta.llm_generation_s) : null;
  const total = meta.duration_s != null ? Number(meta.duration_s) : null;

  if (retrieval == null && llm == null && total == null) return null;

  return (
    <div className="mt-2 d-flex flex-wrap gap-3 small text-body-secondary">
      {retrieval != null && (
        <span><i className="bi bi-search me-1" />{t("history.retrieval")}: {retrieval} ms</span>
      )}
      {llm != null && (
        <span><i className="bi bi-cpu me-1" />{t("history.llmTime")}: {formatDuration(llm)}</span>
      )}
      {total != null && (
        <span><i className="bi bi-stopwatch me-1" />{t("history.totalTime")}: {formatDuration(total)}</span>
      )}
    </div>
  );
}

export default function HistoryPage() {
  const { t } = useTranslation();
  const selectedInstance = useInstanceStore((s) => s.selectedInstance());

  const [data, setData] = useState<PaginatedChatHistory | null>(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<ChatHistoryOut | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await chatApi.history({
        page,
        per_page: PER_PAGE,
        instance_id: selectedInstance?.id,
      });
      setData(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("errors.serverError"));
    } finally {
      setLoading(false);
    }
  }, [page, selectedInstance, t]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleDelete(id: number) {
    if (!confirm(t("history.deleteConfirm"))) return;
    try {
      await chatApi.deleteHistory(id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("errors.serverError"));
    }
  }

  async function handleDeleteAll() {
    if (!confirm(t("history.deleteAllConfirm"))) return;
    try {
      await chatApi.deleteAllHistory(selectedInstance?.id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("errors.serverError"));
    }
  }

  const contextDocs = (detail?.context_docs ?? []) as ContextDoc[];

  return (
    <div className="p-4">
      <div className="d-flex align-items-center justify-content-between mb-4">
        <h4 className="mb-0">
          <i className="bi bi-clock-history me-2" />
          {t("history.title")}
        </h4>
        <div className="d-flex gap-2">
          <Button variant="outline-secondary" size="sm" onClick={load} disabled={loading}>
            <i className="bi bi-arrow-clockwise" />
          </Button>
          {(data?.total ?? 0) > 0 && (
            <Button variant="outline-danger" size="sm" onClick={handleDeleteAll}>
              <i className="bi bi-trash me-1" />
              {t("history.deleteAll")}
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
      ) : !data || data.items.length === 0 ? (
        <div className="text-center py-5 text-body-secondary">
          <i className="bi bi-chat-square-dots fs-1 d-block mb-3" />
          {t("history.empty")}
        </div>
      ) : (
        <>
          <div className="d-flex flex-column gap-3 mb-4">
            {data.items.map((item) => {
              const meta = item.response_metadata;
              const docCount = (item.context_docs ?? []).length;
              return (
                <div
                  key={item.id}
                  className="p-3 rounded border bg-body-secondary"
                  role="button"
                  onClick={() => setDetail(item)}
                  style={{ cursor: "pointer" }}
                >
                  <div className="d-flex justify-content-between align-items-start">
                    <div className="flex-grow-1 me-3">
                      <p className="mb-1 fw-semibold text-truncate">{item.question}</p>
                      <p
                        className="mb-0 small text-body-secondary"
                        style={{
                          display: "-webkit-box",
                          WebkitLineClamp: 2,
                          WebkitBoxOrient: "vertical",
                          overflow: "hidden",
                        }}
                      >
                        {item.answer}
                      </p>
                    </div>
                    <div className="d-flex flex-column align-items-end gap-1 flex-shrink-0">
                      <Badge bg="secondary-subtle" text="secondary" className="text-nowrap">
                        {item.instance_name}
                      </Badge>
                      <small className="text-body-secondary text-nowrap">
                        {new Date(item.created_at).toLocaleString()}
                      </small>
                      <div className="d-flex align-items-center gap-2">
                        {docCount > 0 && (
                          <small className="text-body-secondary text-nowrap">
                            <i className="bi bi-file-earmark-text me-1" />
                            {docCount}
                          </small>
                        )}
                        <DurationChip meta={meta} />
                        <Button
                          variant="link"
                          size="sm"
                          className="p-0 text-danger"
                          onClick={(e) => {
                            e.stopPropagation();
                            void handleDelete(item.id);
                          }}
                        >
                          <i className="bi bi-trash" />
                        </Button>
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {data.total_pages > 1 && (
            <Pagination className="justify-content-center">
              <Pagination.Prev disabled={page === 1} onClick={() => setPage((p) => p - 1)} />
              {Array.from({ length: data.total_pages }, (_, i) => (
                <Pagination.Item
                  key={i + 1}
                  active={i + 1 === page}
                  onClick={() => setPage(i + 1)}
                >
                  {i + 1}
                </Pagination.Item>
              ))}
              <Pagination.Next
                disabled={page === data.total_pages}
                onClick={() => setPage((p) => p + 1)}
              />
            </Pagination>
          )}
        </>
      )}

      {/* Detail Modal */}
      <Modal show={!!detail} onHide={() => setDetail(null)} size="lg" scrollable>
        {detail && (
          <>
            <Modal.Header closeButton>
              <Modal.Title className="fs-6 text-truncate">{detail.question}</Modal.Title>
            </Modal.Header>
            <Modal.Body>
              <div
                className="markdown-body"
                dangerouslySetInnerHTML={{
                  __html: DOMPurify.sanitize(marked.parse(detail.answer) as string),
                }}
              />

              <TimingSection meta={detail.response_metadata} />
              <SourcesSection docs={contextDocs} />
            </Modal.Body>
          </>
        )}
      </Modal>
    </div>
  );
}
