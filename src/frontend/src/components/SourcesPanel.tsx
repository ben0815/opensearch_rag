import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { SourceChunk } from "@/types/api";

interface Props {
  sources: SourceChunk[];
}

const SOURCE_BADGES: Record<string, { label: string; cls: string }> = {
  bm25: { label: "BM25", cls: "bg-primary" },
  knn:  { label: "kNN",  cls: "bg-info text-dark" },
  both: { label: "BM25",  cls: "bg-primary" },
};
const KNN_BOTH_BADGE = { label: "kNN", cls: "bg-info text-dark" };

export default function SourcesPanel({ sources }: Props) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);

  if (sources.length === 0) return null;

  return (
    <div className="sources-panel mt-2 pt-2">
      <button
        type="button"
        className="btn btn-link btn-sm p-0 text-body-secondary text-decoration-none"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <i className={`bi bi-chevron-${open ? "up" : "down"} me-1`} />
        {t("chat.sources")} ({sources.length})
      </button>
      {open && (
        <div className="mt-2 d-flex flex-column gap-2">
          {sources.map((src, i) => (
            <div key={i} className="p-2 rounded bg-body border">
              <div className="d-flex justify-content-between align-items-start mb-1">
                <span className="fw-semibold small text-truncate" style={{ maxWidth: "75%" }}>
                  {src.filename || src.source}
                </span>
                <span className="d-flex align-items-center gap-1 ms-2 text-nowrap flex-shrink-0">
                  {src.search_source && SOURCE_BADGES[src.search_source] && (
                    <>
                      <span
                        className={`badge ${SOURCE_BADGES[src.search_source].cls}`}
                        style={{ fontSize: "0.6rem" }}
                      >
                        {SOURCE_BADGES[src.search_source].label}
                      </span>
                      {src.search_source === "both" && (
                        <span
                          className={`badge ${KNN_BOTH_BADGE.cls}`}
                          style={{ fontSize: "0.6rem" }}
                        >
                          {KNN_BOTH_BADGE.label}
                        </span>
                      )}
                    </>
                  )}
                  <span className="text-body-secondary small">
                    {src.page != null && <>{t("chat.page", { page: src.page })} &middot; </>}
                    {t("chat.score", { score: src.score.toFixed(2) })}
                  </span>
                </span>
              </div>
              <p className="mb-0 small text-body-secondary"
                style={{ display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
                {src.excerpt}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
