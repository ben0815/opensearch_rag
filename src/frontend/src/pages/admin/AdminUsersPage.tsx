import { useCallback, useEffect, useState } from "react";
import { Alert, Badge, Button, Form, InputGroup, Modal, Pagination, Spinner, Table } from "react-bootstrap";
import { useTranslation } from "react-i18next";
import { adminUsers } from "@/api/client";
import { ApiError } from "@/api/client";
import type { AdminUserOut, PaginatedAdminUsers } from "@/types/api";

const PER_PAGE = 20;

export default function AdminUsersPage() {
  const { t } = useTranslation();
  const [data, setData] = useState<PaginatedAdminUsers | null>(null);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<AdminUserOut | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await adminUsers.list({ page, per_page: PER_PAGE, search: search || undefined }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("errors.serverError"));
    } finally {
      setLoading(false);
    }
  }, [page, search, t]);

  useEffect(() => { void load(); }, [load]);

  async function handleToggleAdmin(user: AdminUserOut) {
    setSaving(true);
    try {
      const updated = await adminUsers.patch(user.id, { is_global_admin: !user.is_global_admin });
      setData((d) => d ? { ...d, items: d.items.map((u) => (u.id === updated.id ? updated : u)) } : d);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("errors.serverError"));
    } finally {
      setSaving(false);
    }
  }

  async function handleToggleActive(user: AdminUserOut) {
    setSaving(true);
    try {
      const updated = await adminUsers.patch(user.id, { is_active: !user.is_active });
      setData((d) => d ? { ...d, items: d.items.map((u) => (u.id === updated.id ? updated : u)) } : d);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("errors.serverError"));
    } finally {
      setSaving(false);
    }
  }

  async function handleImpersonate(userId: number) {
    try {
      await adminUsers.impersonate(userId);
      // After impersonation, reload the page to pick up the new session cookie
      window.location.reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("errors.serverError"));
    }
  }

  return (
    <div>
      <div className="d-flex align-items-center justify-content-between mb-4">
        <h4 className="mb-0"><i className="bi bi-people me-2" />{t("admin.users")}</h4>
        <Button variant="outline-secondary" size="sm" onClick={load} disabled={loading}>
          <i className="bi bi-arrow-clockwise" />
        </Button>
      </div>

      {error && <Alert variant="danger" dismissible onClose={() => setError(null)}>{error}</Alert>}

      <InputGroup className="mb-3" style={{ maxWidth: 320 }}>
        <InputGroup.Text><i className="bi bi-search" /></InputGroup.Text>
        <Form.Control
          placeholder={t("common.search")}
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1); }}
        />
      </InputGroup>

      {loading ? (
        <div className="text-center py-5"><Spinner animation="border" /></div>
      ) : (
        <>
          <Table responsive hover>
            <thead>
              <tr>
                <th>UID</th>
                <th>Anzeigename</th>
                <th>Admin</th>
                <th>Aktiv</th>
                <th>Letzter Login</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data?.items.map((user) => (
                <tr key={user.id} style={{ cursor: "pointer" }} onClick={() => setSelected(user)}>
                  <td><code>{user.ldap_uid}</code></td>
                  <td>{user.display_name ?? "—"}</td>
                  <td>
                    <Badge bg={user.is_global_admin ? "danger" : "secondary"}>
                      {user.is_global_admin ? "Admin" : "User"}
                    </Badge>
                  </td>
                  <td>
                    <Badge bg={user.is_active ? "success" : "secondary"}>
                      {user.is_active ? "Aktiv" : "Inaktiv"}
                    </Badge>
                  </td>
                  <td className="small text-body-secondary">
                    {user.last_login ? new Date(user.last_login).toLocaleString() : "—"}
                  </td>
                  <td className="text-end" onClick={(e) => e.stopPropagation()}>
                    <Button
                      variant="outline-secondary"
                      size="sm"
                      className="me-1"
                      title={t("admin.impersonate")}
                      onClick={() => void handleImpersonate(user.id)}
                    >
                      <i className="bi bi-person-badge" />
                    </Button>
                    <Button
                      variant={user.is_global_admin ? "outline-warning" : "outline-primary"}
                      size="sm"
                      className="me-1"
                      disabled={saving}
                      onClick={() => void handleToggleAdmin(user)}
                    >
                      <i className={`bi bi-shield${user.is_global_admin ? "-fill" : ""}`} />
                    </Button>
                    <Button
                      variant={user.is_active ? "outline-danger" : "outline-success"}
                      size="sm"
                      disabled={saving}
                      onClick={() => void handleToggleActive(user)}
                    >
                      <i className={`bi bi-${user.is_active ? "person-slash" : "person-check"}`} />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>

          {(data?.total_pages ?? 0) > 1 && (
            <Pagination className="justify-content-center">
              <Pagination.Prev disabled={page === 1} onClick={() => setPage((p) => p - 1)} />
              {Array.from({ length: data!.total_pages }, (_, i) => (
                <Pagination.Item key={i + 1} active={i + 1 === page} onClick={() => setPage(i + 1)}>
                  {i + 1}
                </Pagination.Item>
              ))}
              <Pagination.Next disabled={page === data!.total_pages} onClick={() => setPage((p) => p + 1)} />
            </Pagination>
          )}
        </>
      )}

      {/* Detail Modal */}
      <Modal show={!!selected} onHide={() => setSelected(null)} size="lg">
        {selected && (
          <>
            <Modal.Header closeButton>
              <Modal.Title>{selected.ldap_uid}</Modal.Title>
            </Modal.Header>
            <Modal.Body>
              <p><strong>E-Mail:</strong> {selected.email ?? "—"}</p>
              <p><strong>Instanzen:</strong></p>
              <ul>
                {selected.instance_memberships.map((m) => (
                  <li key={m.instance_id}>{m.instance_name} ({m.role})</li>
                ))}
              </ul>
              <p><strong>Gruppen:</strong></p>
              <ul>
                {selected.group_names.map((g) => <li key={g}>{g}</li>)}
              </ul>
            </Modal.Body>
          </>
        )}
      </Modal>
    </div>
  );
}
