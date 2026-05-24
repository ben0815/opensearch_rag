import { useCallback, useEffect, useState } from "react";
import { Alert, Badge, Button, Card, Col, Row, Spinner } from "react-bootstrap";
import { useTranslation } from "react-i18next";
import { adminStatus } from "@/api/client";
import type { StatusOut } from "@/types/api";

function StatusCard({ label, status }: { label: string; status: Record<string, unknown> }) {
  const ok = Boolean(status.ok);
  const error = status.error as string | undefined;
  const extras = Object.entries(status).filter(([k]) => k !== "ok" && k !== "error");

  return (
    <Card className={`border-${ok ? "success" : "danger"}`}>
      <Card.Body>
        <div className="d-flex align-items-center justify-content-between mb-2">
          <Card.Title className="mb-0">{label}</Card.Title>
          <Badge bg={ok ? "success" : "danger"}>{ok ? "OK" : "Fehler"}</Badge>
        </div>
        {error && <p className="text-danger small mb-1">{error}</p>}
        {extras.map(([k, v]) => (
          <div key={k} className="small text-body-secondary">
            <span className="fw-semibold me-1">{k}:</span>
            {Array.isArray(v) ? (v as string[]).join(", ") : String(v)}
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
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await adminStatus.get());
    } catch {
      setError(t("errors.serverError"));
    } finally {
      setLoading(false);
    }
  }, [t]);

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

      {error && <Alert variant="danger" dismissible onClose={() => setError(null)}>{error}</Alert>}

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
