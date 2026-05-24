import { useCallback, useEffect, useState } from "react";
import { Badge, Button, Card, Col, Row, Spinner } from "react-bootstrap";
import { useTranslation } from "react-i18next";
import { adminStatus } from "@/api/client";
import type { StatusOut } from "@/types/api";

function StatusCard({ label, status }: { label: string; status: { ok: boolean; error: string | null; extra: Record<string, unknown> } }) {
  return (
    <Card className={`border-${status.ok ? "success" : "danger"}`}>
      <Card.Body>
        <div className="d-flex align-items-center justify-content-between mb-2">
          <Card.Title className="mb-0">{label}</Card.Title>
          <Badge bg={status.ok ? "success" : "danger"}>{status.ok ? "OK" : "Fehler"}</Badge>
        </div>
        {status.error && <p className="text-danger small mb-1">{status.error}</p>}
        {Object.entries(status.extra).map(([k, v]) => (
          <div key={k} className="small text-body-secondary">
            <span className="fw-semibold me-1">{k}:</span>
            {String(v)}
          </div>
        ))}
      </Card.Body>
    </Card>
  );
}

export default function AdminStatusPage() {
  const { t } = useTranslation();
  const [data, setData] = useState<StatusOut | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await adminStatus.get());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  return (
    <div>
      <div className="d-flex align-items-center justify-content-between mb-4">
        <h4 className="mb-0"><i className="bi bi-heart-pulse me-2" />{t("admin.status")}</h4>
        <Button variant="outline-secondary" size="sm" onClick={load} disabled={loading}>
          <i className="bi bi-arrow-clockwise" />
        </Button>
      </div>

      {data && (
        <div className="mb-3 text-body-secondary small">Version: {data.app_version}</div>
      )}

      {loading && !data ? (
        <div className="text-center py-5"><Spinner animation="border" /></div>
      ) : data ? (
        <Row className="g-3">
          <Col md={6}><StatusCard label="OpenSearch" status={data.opensearch} /></Col>
          <Col md={6}><StatusCard label="Ollama" status={data.ollama} /></Col>
          <Col md={6}><StatusCard label="Redis" status={data.redis} /></Col>
          <Col md={6}><StatusCard label="PostgreSQL" status={data.postgres} /></Col>
        </Row>
      ) : null}
    </div>
  );
}
