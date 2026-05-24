import { useCallback, useEffect, useState } from "react";
import { Alert, Button, Form, Modal, Spinner, Table } from "react-bootstrap";
import { useTranslation } from "react-i18next";
import { adminInstances } from "@/api/client";
import { ApiError } from "@/api/client";
import type { InstanceAdminOut } from "@/types/api";

export default function AdminInstancesPage() {
  const { t } = useTranslation();
  const [items, setItems] = useState<InstanceAdminOut[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ name: "", description: "", analyzer: "german" });
  const [creating, setCreating] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await adminInstances.list({ per_page: 100 });
      setItems(resp.items);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("errors.serverError"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { void load(); }, [load]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setCreating(true);
    try {
      await adminInstances.create(form);
      setShowCreate(false);
      setForm({ name: "", description: "", analyzer: "german" });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("errors.serverError"));
    } finally {
      setCreating(false);
    }
  }

  async function handleDelete(inst: InstanceAdminOut) {
    if (!confirm(t("instances.deleteConfirm", { name: inst.name }))) return;
    setDeletingId(inst.id);
    try {
      await adminInstances.delete(inst.id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("errors.serverError"));
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div>
      <div className="d-flex align-items-center justify-content-between mb-4">
        <h4 className="mb-0"><i className="bi bi-collection me-2" />{t("admin.instances")}</h4>
        <div className="d-flex gap-2">
          <Button variant="outline-secondary" size="sm" onClick={load} disabled={loading}>
            <i className="bi bi-arrow-clockwise" />
          </Button>
          <Button size="sm" onClick={() => setShowCreate(true)}>
            <i className="bi bi-plus-circle me-1" />{t("instances.create")}
          </Button>
        </div>
      </div>

      {error && <Alert variant="danger" dismissible onClose={() => setError(null)}>{error}</Alert>}

      {loading ? (
        <div className="text-center py-5"><Spinner animation="border" /></div>
      ) : (
        <Table responsive hover>
          <thead>
            <tr>
              <th>{t("common.name")}</th>
              <th>{t("instances.slug")}</th>
              <th>{t("instances.members")}</th>
              <th>Gruppen</th>
              <th>Dokumente</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {items.map((inst) => (
              <tr key={inst.id}>
                <td>
                  <span className="fw-semibold">{inst.name}</span>
                  {inst.description && (
                    <div className="small text-body-secondary">{inst.description}</div>
                  )}
                </td>
                <td><code>{inst.slug}</code></td>
                <td>{inst.member_count}</td>
                <td>{inst.group_count}</td>
                <td>{inst.doc_count}</td>
                <td className="text-end">
                  <Button
                    variant="outline-danger"
                    size="sm"
                    disabled={deletingId === inst.id}
                    onClick={() => void handleDelete(inst)}
                  >
                    {deletingId === inst.id ? (
                      <Spinner animation="border" size="sm" />
                    ) : (
                      <i className="bi bi-trash" />
                    )}
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}

      {/* Create Modal */}
      <Modal show={showCreate} onHide={() => setShowCreate(false)}>
        <Form onSubmit={handleCreate}>
          <Modal.Header closeButton>
            <Modal.Title>{t("instances.create")}</Modal.Title>
          </Modal.Header>
          <Modal.Body>
            <Form.Group className="mb-3">
              <Form.Label>{t("common.name")}</Form.Label>
              <Form.Control
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                required
              />
            </Form.Group>
            <Form.Group className="mb-3">
              <Form.Label>{t("common.description")}</Form.Label>
              <Form.Control
                as="textarea"
                rows={2}
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              />
            </Form.Group>
            <Form.Group>
              <Form.Label>OpenSearch Analyzer</Form.Label>
              <Form.Select
                value={form.analyzer}
                onChange={(e) => setForm((f) => ({ ...f, analyzer: e.target.value }))}
              >
                <option value="german">german</option>
                <option value="english">english</option>
                <option value="standard">standard</option>
              </Form.Select>
            </Form.Group>
          </Modal.Body>
          <Modal.Footer>
            <Button variant="secondary" onClick={() => setShowCreate(false)}>{t("common.cancel")}</Button>
            <Button type="submit" disabled={creating}>{t("common.save")}</Button>
          </Modal.Footer>
        </Form>
      </Modal>
    </div>
  );
}
