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
            {data.items.map((item) => (
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
                  <div className="d-flex flex-column align-items-end gap-1">
                    <Badge bg="secondary-subtle" text="secondary" className="text-nowrap">
                      {item.instance_name}
                    </Badge>
                    <small className="text-body-secondary text-nowrap">
                      {new Date(item.created_at).toLocaleString()}
                    </small>
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
            ))}
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
              {detail.response_metadata && (
                <div className="mt-3 pt-3 border-top small text-body-secondary">
                  {detail.response_metadata.retrieval_ms !== undefined && (
                    <span className="me-3">
                      Retrieval: {Number(detail.response_metadata.retrieval_ms).toFixed(0)} ms
                    </span>
                  )}
                  {detail.response_metadata.llm_generation_s !== undefined && (
                    <span>
                      LLM: {Number(detail.response_metadata.llm_generation_s).toFixed(1)} s
                    </span>
                  )}
                </div>
              )}
            </Modal.Body>
          </>
        )}
      </Modal>
    </div>
  );
}
