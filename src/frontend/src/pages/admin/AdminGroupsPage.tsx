import { useCallback, useEffect, useState } from "react";
import { Alert, Button, Form, Modal, Pagination, Spinner, Table } from "react-bootstrap";
import { useTranslation } from "react-i18next";
import { adminGroups } from "@/api/client";
import { ApiError } from "@/api/client";
import type { GroupOut, PaginatedGroups } from "@/types/api";

const PER_PAGE = 20;

export default function AdminGroupsPage() {
  const { t } = useTranslation();
  const [data, setData] = useState<PaginatedGroups | null>(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [createName, setCreateName] = useState("");
  const [createDn, setCreateDn] = useState("");
  const [creating, setCreating] = useState(false);
  const [selected, setSelected] = useState<GroupOut | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await adminGroups.list({ page, per_page: PER_PAGE }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("errors.serverError"));
    } finally {
      setLoading(false);
    }
  }, [page, t]);

  useEffect(() => { void load(); }, [load]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setCreating(true);
    try {
      await adminGroups.create({ name: createName, ldap_group_dn: createDn });
      setShowCreate(false);
      setCreateName("");
      setCreateDn("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("errors.serverError"));
    } finally {
      setCreating(false);
    }
  }

  async function handleDelete(id: number) {
    if (!confirm(t("common.delete") + "?")) return;
    try {
      await adminGroups.delete(id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("errors.serverError"));
    }
  }

  return (
    <div>
      <div className="d-flex align-items-center justify-content-between mb-4">
        <h4 className="mb-0"><i className="bi bi-diagram-3 me-2" />{t("admin.groups")}</h4>
        <div className="d-flex gap-2">
          <Button variant="outline-secondary" size="sm" onClick={load} disabled={loading}>
            <i className="bi bi-arrow-clockwise" />
          </Button>
          <Button size="sm" onClick={() => setShowCreate(true)}>
            <i className="bi bi-plus-circle me-1" />{t("common.add")}
          </Button>
        </div>
      </div>

      {error && <Alert variant="danger" dismissible onClose={() => setError(null)}>{error}</Alert>}

      {loading ? (
        <div className="text-center py-5"><Spinner animation="border" /></div>
      ) : (
        <>
          <Table responsive hover>
            <thead>
              <tr>
                <th>{t("common.name")}</th>
                <th>LDAP DN</th>
                <th>Mitglieder</th>
                <th>Instanzen</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data?.items.map((group) => (
                <tr key={group.id} style={{ cursor: "pointer" }} onClick={() => setSelected(group)}>
                  <td>{group.name}</td>
                  <td className="small text-body-secondary text-truncate" style={{ maxWidth: 200 }}>
                    {group.ldap_group_dn ?? "—"}
                  </td>
                  <td>{group.member_ids.length}</td>
                  <td>{group.instance_roles.length}</td>
                  <td className="text-end" onClick={(e) => e.stopPropagation()}>
                    <Button
                      variant="outline-danger"
                      size="sm"
                      onClick={() => void handleDelete(group.id)}
                    >
                      <i className="bi bi-trash" />
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

      {/* Create Modal */}
      <Modal show={showCreate} onHide={() => setShowCreate(false)}>
        <Form onSubmit={handleCreate}>
          <Modal.Header closeButton>
            <Modal.Title>{t("common.add")} Gruppe</Modal.Title>
          </Modal.Header>
          <Modal.Body>
            <Form.Group className="mb-3">
              <Form.Label>{t("common.name")}</Form.Label>
              <Form.Control value={createName} onChange={(e) => setCreateName(e.target.value)} required />
            </Form.Group>
            <Form.Group>
              <Form.Label>LDAP Group DN <small className="text-body-secondary">(optional)</small></Form.Label>
              <Form.Control value={createDn} onChange={(e) => setCreateDn(e.target.value)} />
            </Form.Group>
          </Modal.Body>
          <Modal.Footer>
            <Button variant="secondary" onClick={() => setShowCreate(false)}>{t("common.cancel")}</Button>
            <Button type="submit" disabled={creating}>{t("common.save")}</Button>
          </Modal.Footer>
        </Form>
      </Modal>

      {/* Detail Modal */}
      <Modal show={!!selected} onHide={() => setSelected(null)}>
        {selected && (
          <>
            <Modal.Header closeButton>
              <Modal.Title>{selected.name}</Modal.Title>
            </Modal.Header>
            <Modal.Body>
              <p><strong>Instanzen:</strong></p>
              <ul>
                {selected.instance_roles.map((r) => (
                  <li key={r.instance_id}>{r.instance_name} ({r.role})</li>
                ))}
              </ul>
            </Modal.Body>
          </>
        )}
      </Modal>
    </div>
  );
}
