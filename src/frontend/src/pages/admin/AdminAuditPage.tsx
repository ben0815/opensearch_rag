import { useCallback, useEffect, useState } from "react";
import { Alert, Badge, Button, Form, Pagination, Spinner, Table } from "react-bootstrap";
import { useTranslation } from "react-i18next";
import { adminAudit, ApiError } from "@/api/client";
import type { PaginatedAuditLog } from "@/types/api";

const PER_PAGE = 50;

const ACTION_COLORS: Record<string, string> = {
  login: "success",
  logout: "secondary",
  chat_start: "primary",
  chat_query: "success",
  chat_failed: "danger",
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

type SortCol = "created_at" | "ip_address" | "action" | "user_id";
type SortDir = "asc" | "desc";

function SortTh({
  col,
  label,
  sortCol,
  sortDir,
  onSort,
}: {
  col: SortCol;
  label: string;
  sortCol: SortCol;
  sortDir: SortDir;
  onSort: (col: SortCol) => void;
}) {
  const active = sortCol === col;
  return (
    <th
      style={{ cursor: "pointer", userSelect: "none", whiteSpace: "nowrap" }}
      onClick={() => onSort(col)}
    >
      {label}{" "}
      <i
        className={`bi ${
          active
            ? sortDir === "asc"
              ? "bi-chevron-up"
              : "bi-chevron-down"
            : "bi-chevron-expand text-body-tertiary"
        }`}
      />
    </th>
  );
}

function getPageNumbers(current: number, total: number): (number | "...")[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  const pages: (number | "...")[] = [1];
  if (current > 3) pages.push("...");
  for (let p = Math.max(2, current - 1); p <= Math.min(total - 1, current + 1); p++) {
    if (!pages.includes(p)) pages.push(p);
  }
  if (current < total - 2) pages.push("...");
  if (!pages.includes(total)) pages.push(total);
  return pages;
}

export default function AdminAuditPage() {
  const { t } = useTranslation();
  const [data, setData] = useState<PaginatedAuditLog | null>(null);
  const [page, setPage] = useState(1);
  const [action, setAction] = useState("");
  const [username, setUsername] = useState("");
  const [ip, setIp] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [sortCol, setSortCol] = useState<SortCol>("created_at");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [debouncedUsername, setDebouncedUsername] = useState("");
  const [debouncedIp, setDebouncedIp] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const id = setTimeout(() => setDebouncedUsername(username), 400);
    return () => clearTimeout(id);
  }, [username]);

  useEffect(() => {
    const id = setTimeout(() => setDebouncedIp(ip), 400);
    return () => clearTimeout(id);
  }, [ip]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(
        await adminAudit.list({
          page,
          per_page: PER_PAGE,
          action: action || undefined,
          username: debouncedUsername || undefined,
          ip: debouncedIp || undefined,
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
          order_by: sortCol,
          order_dir: sortDir,
        }),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("errors.serverError"));
    } finally {
      setLoading(false);
    }
  }, [page, action, debouncedUsername, debouncedIp, dateFrom, dateTo, sortCol, sortDir, t]);

  useEffect(() => { void load(); }, [load]);

  const handleSort = (col: SortCol) => {
    if (col === sortCol) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortCol(col);
      setSortDir("desc");
    }
    setPage(1);
  };

  const resetFilters = () => {
    setAction("");
    setUsername("");
    setIp("");
    setDateFrom("");
    setDateTo("");
    setPage(1);
  };

  const hasFilters = !!(action || username || ip || dateFrom || dateTo);
  const totalPages = data?.total_pages ?? 1;
  const pageNums = getPageNumbers(page, totalPages);

  return (
    <div>
      <div className="d-flex align-items-center justify-content-between mb-4">
        <h4 className="mb-0">
          <i className="bi bi-list-check me-2" />
          {t("admin.audit")}
        </h4>
        <Button variant="outline-secondary" size="sm" onClick={load} disabled={loading}>
          <i className="bi bi-arrow-clockwise" />
        </Button>
      </div>

      {error && (
        <Alert variant="danger" dismissible onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      <div className="d-flex flex-wrap gap-2 mb-3 align-items-end">
        <Form.Select
          size="sm"
          style={{ maxWidth: 200 }}
          value={action}
          onChange={(e) => { setAction(e.target.value); setPage(1); }}
        >
          <option value="">Alle Aktionen</option>
          {Object.keys(ACTION_COLORS).map((a) => (
            <option key={a} value={a}>{a}</option>
          ))}
        </Form.Select>

        <Form.Control
          size="sm"
          type="text"
          placeholder="Benutzer"
          style={{ maxWidth: 160 }}
          value={username}
          onChange={(e) => { setUsername(e.target.value); setPage(1); }}
        />

        <Form.Control
          size="sm"
          type="text"
          placeholder="IP-Adresse"
          style={{ maxWidth: 140 }}
          value={ip}
          onChange={(e) => { setIp(e.target.value); setPage(1); }}
        />

        <Form.Control
          size="sm"
          type="date"
          style={{ maxWidth: 155 }}
          value={dateFrom}
          title="Von"
          onChange={(e) => { setDateFrom(e.target.value); setPage(1); }}
        />

        <Form.Control
          size="sm"
          type="date"
          style={{ maxWidth: 155 }}
          value={dateTo}
          title="Bis"
          onChange={(e) => { setDateTo(e.target.value); setPage(1); }}
        />

        {hasFilters && (
          <Button variant="outline-secondary" size="sm" onClick={resetFilters}>
            <i className="bi bi-x-circle me-1" />
            Zurücksetzen
          </Button>
        )}
      </div>

      {loading ? (
        <div className="text-center py-5">
          <Spinner animation="border" />
        </div>
      ) : (
        <>
          <Table responsive hover className="small">
            <thead>
              <tr>
                <SortTh col="created_at" label="Zeit" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} />
                <SortTh col="action" label="Aktion" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} />
                <SortTh col="user_id" label="Benutzer" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} />
                <th>Ziel</th>
                <SortTh col="ip_address" label="IP" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} />
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
                  <td>{entry.ldap_uid ?? (entry.user_id != null ? String(entry.user_id) : "—")}</td>
                  <td>
                    {entry.target_type && (
                      <span className="text-body-secondary">
                        {entry.target_type}/{entry.target_id}
                      </span>
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

          {totalPages > 1 && (
            <Pagination className="justify-content-center flex-wrap">
              <Pagination.Prev disabled={page === 1} onClick={() => setPage((p) => p - 1)} />
              {pageNums.map((p, i) =>
                p === "..." ? (
                  <Pagination.Ellipsis key={`e${i}`} disabled />
                ) : (
                  <Pagination.Item key={p} active={p === page} onClick={() => setPage(p as number)}>
                    {p}
                  </Pagination.Item>
                ),
              )}
              <Pagination.Next disabled={page === totalPages} onClick={() => setPage((p) => p + 1)} />
            </Pagination>
          )}
        </>
      )}
    </div>
  );
}
