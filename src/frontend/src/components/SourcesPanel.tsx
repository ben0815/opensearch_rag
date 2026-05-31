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
  const [panelOpen, setPanelOpen] = useState(false);
  const [expandedSet, setExpandedSet] = useState<Set<number>>(new Set());

  if (sources.length === 0) return null;

  function toggleSource(i: number) {
    setExpandedSet((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });
  }

  return (
    <div className="sources-panel mt-2 pt-2">
      <button
        type="button"
        className="btn btn-link btn-sm p-0 text-body-secondary text-decoration-none"
        onClick={() => setPanelOpen((o) => !o)}
        aria-expanded={panelOpen}
      >
        <i className={`bi bi-chevron-${panelOpen ? "up" : "down"} me-1`} />
        {t("chat.sources")} ({sources.length})
      </button>
      {panelOpen && (
        <div className="mt-2 d-flex flex-column gap-2">
          {sources.map((src, i) => {
            const isExpanded = expandedSet.has(i);
            return (
              <div key={i} className="rounded bg-body border overflow-hidden">
                <div
                  className="d-flex justify-content-between align-items-start p-2"
                  style={{ cursor: "pointer" }}
                  onClick={() => toggleSource(i)}
                  role="button"
                  aria-expanded={isExpanded}
                  tabIndex={0}
                  onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && toggleSource(i)}
                >
                  <span className="fw-semibold small text-truncate" style={{ maxWidth: "72%" }}>
                    {src.filename || src.source}
                  </span>
                  <span className="d-flex align-items-center gap-1 ms-2 text-nowrap flex-shrink-0">
                    {src.search_source && SOURCE_BADGES[src.search_source] && (
                      <>
                        <span className={`badge ${SOURCE_BADGES[src.search_source].cls}`} style={{ fontSize: "0.6rem" }}>
                          {SOURCE_BADGES[src.search_source].label}
                        </span>
                        {src.search_source === "both" && (
                          <span className={`badge ${KNN_BOTH_BADGE.cls}`} style={{ fontSize: "0.6rem" }}>
                            {KNN_BOTH_BADGE.label}
                          </span>
                        )}
                      </>
                    )}
                    <span className="text-body-secondary small">
                      {src.page != null && <>{t("chat.page", { page: src.page })} &middot; </>}
                      {t("chat.score", { score: src.score.toFixed(2) })}
                    </span>
                    <i className={`bi bi-chevron-${isExpanded ? "up" : "down"} small text-body-secondary ms-1`} />
                  </span>
                </div>
                {isExpanded ? (
                  <div
                    className="px-2 pb-2 pt-2 small text-body-secondary"
                    style={{
                      whiteSpace: "pre-wrap",
                      maxHeight: "260px",
                      overflowY: "auto",
                      borderTop: "1px solid var(--bs-border-color)",
                    }}
                  >
                    {src.excerpt}
                  </div>
                ) : (
                  <p
                    className="mb-0 px-2 pb-2 small text-body-secondary"
                    style={{
                      display: "-webkit-box",
                      WebkitLineClamp: 2,
                      WebkitBoxOrient: "vertical",
                      overflow: "hidden",
                    }}
                  >
                    {src.excerpt}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
