import { useState } from "react";
import { Collapse } from "react-bootstrap";
import { useTranslation } from "react-i18next";
import type { SourceChunk } from "@/types/api";

interface Props {
  sources: SourceChunk[];
}

export default function SourcesPanel({ sources }: Props) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);

  if (sources.length === 0) return null;

  return (
    <div className="sources-panel mt-2 pt-2">
      <button
        className="btn btn-link btn-sm p-0 text-body-secondary text-decoration-none"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <i className={`bi bi-chevron-${open ? "up" : "down"} me-1`} />
        {t("chat.sources")} ({sources.length})
      </button>
      <Collapse in={open}>
        <div className="mt-2 d-flex flex-column gap-2">
          {sources.map((src, i) => (
            <div key={i} className="p-2 rounded bg-body border">
              <div className="d-flex justify-content-between align-items-start mb-1">
                <span className="fw-semibold small text-truncate" style={{ maxWidth: "75%" }}>
                  {src.source}
                </span>
                <span className="text-body-secondary small ms-2 text-nowrap">
                  {t("chat.page", { page: src.page })} &middot;{" "}
                  {t("chat.score", { score: src.score.toFixed(2) })}
                </span>
              </div>
              <p className="mb-0 small text-body-secondary"
                style={{ display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
                {src.text}
              </p>
            </div>
          ))}
        </div>
      </Collapse>
    </div>
  );
}
