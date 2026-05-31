import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Badge, Button, Form, InputGroup, Modal, Pagination, Spinner, Table } from "react-bootstrap";
import { useTranslation } from "react-i18next";
import { adminUsers, adminLdap } from "@/api/client";
import { ApiError } from "@/api/client";
import type { AdminUserOut, LDAPSearchResult, PaginatedAdminUsers } from "@/types/api";

const PER_PAGE = 20;

interface CreateModalState {
  open: boolean;
  ldapUid: string;
  displayName: string;
  email: string;
  isAdmin: boolean;
  searching: boolean;
  searchQuery: string;
  searchResults: LDAPSearchResult[];
  searchError: string | null;
  saving: boolean;
  error: string | null;
}

const EMPTY_CREATE: CreateModalState = {
  open: false, ldapUid: "", displayName: "", email: "", isAdmin: false,
  searching: false, searchQuery: "", searchResults: [], searchError: null,
  saving: false, error: null,
};

export default function AdminUsersPage() {
  const { t } = useTranslation();
  const [data, setData] = useState<PaginatedAdminUsers | null>(null);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<AdminUserOut | null>(null);
  const [saving, setSaving] = useState(false);
  const [createModal, setCreateModal] = useState<CreateModalState>(EMPTY_CREATE);
  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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
    const action = user.is_global_admin ? "Admin-Rechte entziehen" : "Admin-Rechte vergeben";
    if (!confirm(`${action}: ${user.ldap_uid}?`)) return;
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
    const action = user.is_active ? "Benutzer deaktivieren" : "Benutzer aktivieren";
    if (!confirm(`${action}: ${user.ldap_uid}?`)) return;
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

  async function handleImpersonate(user: AdminUserOut) {
    if (!confirm(`Als ${user.ldap_uid} (${user.display_name ?? "kein Name"}) anmelden? Die aktuelle Admin-Session wird durch eine Impersonations-Session ersetzt.`)) return;
    try {
      await adminUsers.impersonate(user.id);
      window.location.reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("errors.serverError"));
    }
  }

  function handleSearchQueryChange(q: string) {
    setCreateModal((m) => ({ ...m, searchQuery: q, searchError: null }));
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    searchTimerRef.current = setTimeout(() => { void runLdapSearch(q); }, 400);
  }

  async function runLdapSearch(q: string) {
    setCreateModal((m) => ({ ...m, searching: true, searchResults: [], searchError: null }));
    try {
      const results = await adminLdap.search(q);
      setCreateModal((m) => ({ ...m, searching: false, searchResults: results }));
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : t("errors.serverError");
      setCreateModal((m) => ({ ...m, searching: false, searchResults: [], searchError: msg }));
    }
  }

  function selectLdapResult(r: LDAPSearchResult) {
    setCreateModal((m) => ({
      ...m, ldapUid: r.ldap_uid,
      displayName: r.display_name ?? "", email: r.email ?? "",
      searchResults: [], searchQuery: "",
    }));
  }

  async function handleCreateUser(e: React.FormEvent) {
    e.preventDefault();
    setCreateModal((m) => ({ ...m, saving: true, error: null }));
    try {
      await adminUsers.create({
        ldap_uid: createModal.ldapUid.trim(),
        display_name: createModal.displayName.trim() || null,
        email: createModal.email.trim() || null,
        is_global_admin: createModal.isAdmin,
      });
      setCreateModal(EMPTY_CREATE);
      await load();
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : t("errors.serverError");
      setCreateModal((m) => ({ ...m, saving: false, error: msg }));
    }
  }

  return (
    <div>
      <div className="d-flex align-items-center justify-content-between mb-4">
        <h4 className="mb-0"><i className="bi bi-people me-2" />{t("admin.users")}</h4>
        <div className="d-flex gap-2">
          <Button variant="primary" size="sm" onClick={() => setCreateModal({ ...EMPTY_CREATE, open: true })}>
            <i className="bi bi-person-plus me-1" />Benutzer anlegen
          </Button>
          <Button variant="outline-secondary" size="sm" onClick={load} disabled={loading}>
            <i className="bi bi-arrow-clockwise" />
          </Button>
        </div>
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
                      onClick={() => void handleImpersonate(user)}
                    >
                      <i className="bi bi-person-badge" />
                    </Button>
                    <Button
                      variant={user.is_global_admin ? "outline-warning" : "outline-primary"}
                      size="sm"
                      className="me-1"
                      title={user.is_global_admin ? t("admin.toggleAdminRevoke") : t("admin.toggleAdminGrant")}
                      disabled={saving}
                      onClick={() => void handleToggleAdmin(user)}
                    >
                      <i className={`bi bi-shield${user.is_global_admin ? "-fill" : ""}`} />
                    </Button>
                    <Button
                      variant={user.is_active ? "outline-danger" : "outline-success"}
                      size="sm"
                      title={user.is_active ? t("admin.toggleActiveDeactivate") : t("admin.toggleActiveActivate")}
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

      {/* Create User Modal */}
      <Modal show={createModal.open} onHide={() => setCreateModal(EMPTY_CREATE)} size="lg">
        <Modal.Header closeButton>
          <Modal.Title><i className="bi bi-person-plus me-2" />Benutzer anlegen</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          {createModal.error && (
            <Alert variant="danger" dismissible onClose={() => setCreateModal((m) => ({ ...m, error: null }))}>
              {createModal.error}
            </Alert>
          )}

          {/* LDAP Search */}
          <Form.Group className="mb-3">
            <Form.Label><i className="bi bi-search me-1" />LDAP durchsuchen</Form.Label>
            <InputGroup>
              <Form.Control
                placeholder="Name, UID oder E-Mail eingeben…"
                value={createModal.searchQuery}
                onChange={(e) => handleSearchQueryChange(e.target.value)}
              />
              {createModal.searching && (
                <InputGroup.Text><Spinner animation="border" size="sm" /></InputGroup.Text>
              )}
            </InputGroup>
            {createModal.searchError && (
              <Form.Text className="text-danger">{createModal.searchError}</Form.Text>
            )}
            {createModal.searchResults.length > 0 && (
              <div className="border rounded mt-1" style={{ maxHeight: 200, overflowY: "auto" }}>
                {createModal.searchResults.map((r) => (
                  <button
                    key={r.ldap_uid}
                    type="button"
                    className="d-block w-100 text-start px-3 py-2 border-0 bg-transparent"
                    style={{ cursor: "pointer" }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bs-secondary-bg)")}
                    onMouseLeave={(e) => (e.currentTarget.style.background = "")}
                    onClick={() => selectLdapResult(r)}
                  >
                    <code className="me-2">{r.ldap_uid}</code>
                    <span className="text-body-secondary small">{r.display_name ?? ""}{r.email ? ` — ${r.email}` : ""}</span>
                  </button>
                ))}
              </div>
            )}
          </Form.Group>

          <hr />

          {/* Manual entry / pre-filled form */}
          <Form id="create-user-form" onSubmit={handleCreateUser}>
            <Form.Group className="mb-3">
              <Form.Label>LDAP UID <span className="text-danger">*</span></Form.Label>
              <Form.Control
                required
                value={createModal.ldapUid}
                onChange={(e) => setCreateModal((m) => ({ ...m, ldapUid: e.target.value }))}
                placeholder="z. B. jsmith"
              />
              <Form.Text className="text-body-secondary">Muss exakt mit dem uid-Attribut in LDAP übereinstimmen.</Form.Text>
            </Form.Group>
            <Form.Group className="mb-3">
              <Form.Label>Anzeigename</Form.Label>
              <Form.Control
                value={createModal.displayName}
                onChange={(e) => setCreateModal((m) => ({ ...m, displayName: e.target.value }))}
                placeholder="Wird beim ersten Login aus LDAP überschrieben"
              />
            </Form.Group>
            <Form.Group className="mb-3">
              <Form.Label>E-Mail</Form.Label>
              <Form.Control
                type="email"
                value={createModal.email}
                onChange={(e) => setCreateModal((m) => ({ ...m, email: e.target.value }))}
                placeholder="Wird beim ersten Login aus LDAP überschrieben"
              />
            </Form.Group>
            <Form.Check
              type="switch"
              label="Global-Admin"
              checked={createModal.isAdmin}
              onChange={(e) => setCreateModal((m) => ({ ...m, isAdmin: e.target.checked }))}
              className="mb-3"
            />
          </Form>
        </Modal.Body>
        <Modal.Footer>
          <Button variant="secondary" onClick={() => setCreateModal(EMPTY_CREATE)}>Abbrechen</Button>
          <Button type="submit" form="create-user-form" disabled={createModal.saving || !createModal.ldapUid.trim()}>
            {createModal.saving && <Spinner animation="border" size="sm" className="me-2" />}
            Benutzer anlegen
          </Button>
        </Modal.Footer>
      </Modal>

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
