import { useCallback, useEffect, useState } from "react";
import { Alert, Badge, Button, Form, InputGroup, Pagination, Spinner, Table } from "react-bootstrap";
import { useTranslation } from "react-i18next";
import { adminAudit } from "@/api/client";
import { ApiError } from "@/api/client";
import type { PaginatedAuditLog } from "@/types/api";

const PER_PAGE = 50;

const ACTION_COLORS: Record<string, string> = {
  login: "success",
  logout: "secondary",
  doc_upload: "primary",
  doc_delete: "danger",
  instance_create: "info",
  instance_delete: "danger",
  instance_patch: "secondary",
  instance_member_add: "info",
  instance_member_remove: "warning",
  group_create: "info",
  group_delete: "danger",
  user_pre_create: "info",
  user_patch: "warning",
  user_delete: "danger",
  settings_change: "warning",
  ldap_config_change: "warning",
  ldap_sync: "secondary",
  impersonation_start: "danger",
  impersonation_stop: "secondary",
  maintenance_mode_change: "warning",
};

export default function AdminAuditPage() {
  const { t } = useTranslation();
  const [data, setData] = useState<PaginatedAuditLog | null>(null);
  const [page, setPage] = useState(1);
  const [action, setAction] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(
        await adminAudit.list({
          page,
          per_page: PER_PAGE,
          action: action || undefined,
        }),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("errors.serverError"));
    } finally {
      setLoading(false);
    }
  }, [page, action, t]);

  useEffect(() => { void load(); }, [load]);

  return (
    <div>
      <div className="d-flex align-items-center justify-content-between mb-4">
        <h4 className="mb-0"><i className="bi bi-list-check me-2" />{t("admin.audit")}</h4>
        <Button variant="outline-secondary" size="sm" onClick={load} disabled={loading}>
          <i className="bi bi-arrow-clockwise" />
        </Button>
      </div>

      {error && <Alert variant="danger" dismissible onClose={() => setError(null)}>{error}</Alert>}

      <InputGroup className="mb-3" style={{ maxWidth: 280 }}>
        <Form.Select
          value={action}
          onChange={(e) => { setAction(e.target.value); setPage(1); }}
        >
          <option value="">Alle Aktionen</option>
          {Object.keys(ACTION_COLORS).map((a) => (
            <option key={a} value={a}>{a}</option>
          ))}
        </Form.Select>
      </InputGroup>

      {loading ? (
        <div className="text-center py-5"><Spinner animation="border" /></div>
      ) : (
        <>
          <Table responsive hover className="small">
            <thead>
              <tr>
                <th>Zeit</th>
                <th>Aktion</th>
                <th>Benutzer</th>
                <th>Ziel</th>
                <th>IP</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {data?.items.map((entry) => (
                <tr key={entry.id}>
                  <td className="text-nowrap text-body-secondary">
                    {new Date(entry.created_at).toLocaleString()}
                  </td>
                  <td>
                    <Badge bg={ACTION_COLORS[entry.action] ?? "secondary"}>
                      {entry.action}
                    </Badge>
                  </td>
                  <td>{entry.user_id ?? "—"}</td>
                  <td>
                    {entry.target_type && (
                      <span>{entry.target_type}/{entry.target_id}</span>
                    )}
                  </td>
                  <td className="text-body-secondary">{entry.ip_address ?? "—"}</td>
                  <td>
                    {entry.detail && (
                      <code className="text-body-secondary small">
                        {JSON.stringify(entry.detail)}
                      </code>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>

          {(data?.total_pages ?? 0) > 1 && (
            <Pagination className="justify-content-center">
              <Pagination.Prev disabled={page === 1} onClick={() => setPage((p) => p - 1)} />
              {Array.from({ length: Math.min(data!.total_pages, 10) }, (_, i) => (
                <Pagination.Item key={i + 1} active={i + 1 === page} onClick={() => setPage(i + 1)}>
                  {i + 1}
                </Pagination.Item>
              ))}
              <Pagination.Next disabled={page === data!.total_pages} onClick={() => setPage((p) => p + 1)} />
            </Pagination>
          )}
        </>
      )}
    </div>
  );
}
