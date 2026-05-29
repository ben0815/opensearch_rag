import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Badge, Button, Collapse, Form, Modal, Nav, Spinner, Tab, Table } from "react-bootstrap";
import { useTranslation } from "react-i18next";
import { adminInstances, adminUsers } from "@/api/client";
import { ApiError } from "@/api/client";
import type { AdminUserOut, InstanceAdminOut, InstanceMemberOut } from "@/types/api";

// ─── Icon + Color config ──────────────────────────────────────────────────────

const ICONS = [
  { value: "bi-folder2", label: "Ordner" },
  { value: "bi-file-earmark-text", label: "Dokument" },
  { value: "bi-book", label: "Buch" },
  { value: "bi-briefcase", label: "Koffer" },
  { value: "bi-building", label: "Gebäude" },
  { value: "bi-bank", label: "Bank" },
  { value: "bi-people", label: "Personen" },
  { value: "bi-gear", label: "Einstellungen" },
  { value: "bi-clipboard", label: "Zwischenablage" },
  { value: "bi-journal", label: "Journal" },
  { value: "bi-archive", label: "Archiv" },
  { value: "bi-layers", label: "Ebenen" },
  { value: "bi-database", label: "Datenbank" },
  { value: "bi-mortarboard", label: "Bildung" },
  { value: "bi-hospital", label: "Krankenhaus" },
  { value: "bi-shield", label: "Schild" },
  { value: "bi-globe", label: "Welt" },
  { value: "bi-house", label: "Haus" },
  { value: "bi-star", label: "Stern" },
  { value: "bi-wrench", label: "Werkzeug" },
  { value: "bi-truck", label: "Fahrzeug" },
  { value: "bi-graph-up", label: "Statistik" },
];

const PALETTE = [
  "#4a90d9", "#e74c3c", "#2ecc71", "#f39c12", "#9b59b6",
  "#1abc9c", "#e67e22", "#34495e", "#e91e63", "#00bcd4",
  "#8bc34a", "#795548",
];

const DEFAULT_ICON = "bi-folder2";
const DEFAULT_COLOR = "#4a90d9";

function instIcon(inst: InstanceAdminOut) {
  return String(inst.settings?.icon ?? DEFAULT_ICON);
}
function instColor(inst: InstanceAdminOut) {
  return String(inst.settings?.color ?? DEFAULT_COLOR);
}

function InstanceBadge({ inst }: { inst: InstanceAdminOut }) {
  return (
    <span
      className="d-inline-flex align-items-center justify-content-center rounded me-2 flex-shrink-0"
      style={{ width: 30, height: 30, background: instColor(inst), color: "#fff" }}
    >
      <i className={`bi ${instIcon(inst)}`} style={{ fontSize: 14 }} />
    </span>
  );
}

// ─── Per-instance prompt field ────────────────────────────────────────────────

const PROMPT_PLACEHOLDERS = ["{context}", "{question}", "{history}"] as const;

function InstancePromptField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [showHelp, setShowHelp] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const hasContent = value.trim().length > 0;
  const missingPlaceholders = hasContent
    ? PROMPT_PLACEHOLDERS.filter((p) => !value.includes(p))
    : [];

  function insertPlaceholder(placeholder: string) {
    const el = textareaRef.current;
    if (!el) { onChange(value + placeholder); return; }
    const start = el.selectionStart ?? value.length;
    const end = el.selectionEnd ?? value.length;
    const next = value.slice(0, start) + placeholder + value.slice(end);
    onChange(next);
    requestAnimationFrame(() => {
      el.selectionStart = start + placeholder.length;
      el.selectionEnd = start + placeholder.length;
      el.focus();
    });
  }

  return (
    <Form.Group>
      {/* Label row */}
      <div className="d-flex align-items-center gap-1 mb-1">
        <Form.Label className="small mb-0 fw-semibold">System-Prompt (Instanz-Override)</Form.Label>
        <button
          type="button"
          onClick={() => setShowHelp((v) => !v)}
          title="Hilfe anzeigen"
          style={{
            width: 16, height: 16, borderRadius: "50%", border: "1.5px solid",
            borderColor: showHelp ? "var(--bs-primary)" : "var(--bs-secondary-color)",
            background: showHelp ? "var(--bs-primary)" : "transparent",
            color: showHelp ? "#fff" : "var(--bs-secondary-color)",
            fontSize: 9, fontWeight: 700, lineHeight: 1, cursor: "pointer", flexShrink: 0,
          }}
        >
          ?
        </button>
        {hasContent && (
          <button
            type="button"
            className="btn btn-link btn-sm p-0 text-danger ms-auto"
            title="Zurücksetzen — globaler System-Prompt wird verwendet"
            onClick={() => onChange("")}
          >
            <i className="bi bi-arrow-counterclockwise me-1" style={{ fontSize: 12 }} />
            <span style={{ fontSize: "0.75rem" }}>Zurücksetzen</span>
          </button>
        )}
      </div>

      {/* Collapsible help */}
      <Collapse in={showHelp}>
        <div>
          <Alert variant="info" className="py-2 px-2 small mb-2">
            <strong>Überschreibt den globalen System-Prompt nur für diese Instanz.</strong><br />
            Leer lassen = globaler Prompt wird verwendet. Kein Neustart nötig.<br />
            Qwen3: <code>/no_think</code> am Anfang verhindert den Thinking-Modus.
          </Alert>
        </div>
      </Collapse>

      {/* Always-visible placeholder chips */}
      <div
        className="d-flex align-items-center flex-wrap gap-1 mb-1 px-2 py-1 rounded"
        style={{ background: "var(--bs-tertiary-bg)", border: "1px solid var(--bs-border-color)" }}
      >
        <span className="text-body-secondary" style={{ fontSize: "0.72rem", whiteSpace: "nowrap" }}>Pflicht:</span>
        {PROMPT_PLACEHOLDERS.map((p) => {
          const missing = hasContent && !value.includes(p);
          return (
            <button
              key={p}
              type="button"
              onClick={() => insertPlaceholder(p)}
              title={missing ? `${p} fehlt — klicken zum Einfügen` : `${p} einfügen`}
              style={{
                fontFamily: "monospace", fontSize: "0.72rem",
                padding: "0 5px", borderRadius: 3,
                border: `1px solid ${missing ? "var(--bs-danger)" : "var(--bs-secondary-color)"}`,
                background: missing ? "var(--bs-danger-bg-subtle)" : "var(--bs-secondary-bg)",
                color: missing ? "var(--bs-danger-text-emphasis)" : "var(--bs-body-color)",
                cursor: "pointer",
              }}
            >
              {missing && <i className="bi bi-exclamation-triangle-fill me-1" style={{ fontSize: 9 }} />}
              {p}
            </button>
          );
        })}
        <span className="text-body-secondary ms-1" style={{ fontSize: "0.7rem" }}>klicken = einfügen</span>
      </div>

      {/* Textarea */}
      <Form.Control
        ref={textareaRef as React.Ref<HTMLTextAreaElement>}
        as="textarea"
        rows={6}
        size="sm"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="(leer = globaler System-Prompt wird verwendet)"
        isInvalid={missingPlaceholders.length > 0}
        style={{ fontFamily: "monospace", fontSize: "0.8rem", resize: "vertical" }}
      />

      {/* Live validation */}
      {missingPlaceholders.length > 0 && (
        <div className="text-danger mt-1" style={{ fontSize: "0.78rem" }}>
          <i className="bi bi-exclamation-triangle-fill me-1" />
          Fehlend:{" "}
          {missingPlaceholders.map((p) => <code key={p} className="me-1">{p}</code>)}
        </div>
      )}

      {/* Empty state */}
      {!hasContent && (
        <div className="text-body-secondary mt-1" style={{ fontSize: "0.75rem" }}>
          <i className="bi bi-info-circle me-1" />
          Kein Instanz-Prompt — globaler System-Prompt ist aktiv.
        </div>
      )}
    </Form.Group>
  );
}

// ─── Edit form ────────────────────────────────────────────────────────────────

const OVERRIDE_KEYS = ["llm_model", "llm_temperature", "llm_num_ctx", "hybrid_k", "hybrid_score_threshold", "hybrid_bm25_weight", "llm_system_prompt"] as const;

function countOverrides(settings: Record<string, unknown> | null): number {
  if (!settings) return 0;
  return OVERRIDE_KEYS.filter((k) => {
    const v = settings[k];
    return v != null && v !== "";
  }).length;
}

type EditForm = {
  name: string;
  description: string;
  icon: string;
  color: string;
  llm_model: string;
  llm_temperature: string;
  llm_num_ctx: string;
  hybrid_k: string;
  hybrid_score_threshold: string;
  hybrid_bm25_weight: string;
  llm_system_prompt: string;
};

function editFormFromInst(inst: InstanceAdminOut): EditForm {
  const s = inst.settings ?? {};
  return {
    name: inst.name,
    description: inst.description ?? "",
    icon: String(s.icon ?? DEFAULT_ICON),
    color: String(s.color ?? DEFAULT_COLOR),
    llm_model: String(s.llm_model ?? ""),
    llm_temperature: s.llm_temperature != null ? String(s.llm_temperature) : "",
    llm_num_ctx: s.llm_num_ctx != null ? String(s.llm_num_ctx) : "",
    hybrid_k: s.hybrid_k != null ? String(s.hybrid_k) : "",
    hybrid_score_threshold: s.hybrid_score_threshold != null ? String(s.hybrid_score_threshold) : "",
    hybrid_bm25_weight: s.hybrid_bm25_weight != null ? String(s.hybrid_bm25_weight) : "",
    llm_system_prompt: s.llm_system_prompt ? String(s.llm_system_prompt) : "",
  };
}

// ─── Member state ─────────────────────────────────────────────────────────────

interface MembersState {
  list: InstanceMemberOut[];
  loading: boolean;
  error: string | null;
  searchQ: string;
  searchResults: AdminUserOut[];
  searching: boolean;
  selectedUser: AdminUserOut | null;
  addRole: "viewer" | "manager";
  adding: boolean;
  addError: string | null;
}

const EMPTY_MEMBERS: MembersState = {
  list: [], loading: false, error: null,
  searchQ: "", searchResults: [], searching: false,
  selectedUser: null, addRole: "viewer", adding: false, addError: null,
};

// ─── Main component ───────────────────────────────────────────────────────────

export default function AdminInstancesPage() {
  const { t } = useTranslation();
  const [items, setItems] = useState<InstanceAdminOut[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Create
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ name: "", description: "", analyzer: "german" });
  const [creating, setCreating] = useState(false);

  // Edit
  const [editingInst, setEditingInst] = useState<InstanceAdminOut | null>(null);
  const [editForm, setEditForm] = useState<EditForm | null>(null);
  const [saving, setSaving] = useState(false);
  const [activeTab, setActiveTab] = useState("settings");

  // Members
  const [members, setMembers] = useState<MembersState>(EMPTY_MEMBERS);
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Delete
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setItems(await adminInstances.list());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("errors.serverError"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { void load(); }, [load]);

  async function loadMembers(instanceId: number) {
    setMembers((m) => ({ ...m, loading: true, error: null }));
    try {
      const list = await adminInstances.members(instanceId);
      setMembers((m) => ({ ...m, loading: false, list }));
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : t("errors.serverError");
      setMembers((m) => ({ ...m, loading: false, error: msg }));
    }
  }

  function openEdit(inst: InstanceAdminOut) {
    setEditingInst(inst);
    setEditForm(editFormFromInst(inst));
    setActiveTab("settings");
    setMembers(EMPTY_MEMBERS);
    void loadMembers(inst.id);
  }

  function closeEdit() {
    setEditingInst(null);
    setEditForm(null);
    setMembers(EMPTY_MEMBERS);
  }

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

  async function handleSaveEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!editingInst || !editForm) return;
    setSaving(true);
    try {
      const settings: Record<string, unknown> = {
        icon: editForm.icon,
        color: editForm.color,
      };
      if (editForm.llm_model.trim()) settings.llm_model = editForm.llm_model.trim();
      if (editForm.llm_temperature.trim()) settings.llm_temperature = parseFloat(editForm.llm_temperature.replace(",", "."));
      if (editForm.llm_num_ctx.trim()) settings.llm_num_ctx = parseInt(editForm.llm_num_ctx, 10);
      if (editForm.hybrid_k.trim()) settings.hybrid_k = parseInt(editForm.hybrid_k, 10);
      if (editForm.hybrid_score_threshold.trim()) settings.hybrid_score_threshold = parseFloat(editForm.hybrid_score_threshold.replace(",", "."));
      settings.hybrid_bm25_weight = editForm.hybrid_bm25_weight.trim() || "";
      if (editForm.llm_system_prompt.trim()) settings.llm_system_prompt = editForm.llm_system_prompt.trim();

      await adminInstances.patch(editingInst.id, {
        name: editForm.name.trim(),
        description: editForm.description.trim(),
        settings,
      });
      closeEdit();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("errors.serverError"));
    } finally {
      setSaving(false);
    }
  }

  async function handleClearOverrides() {
    if (!editingInst || !editForm) return;
    setSaving(true);
    try {
      await adminInstances.patch(editingInst.id, {
        settings: { icon: editForm.icon, color: editForm.color },
      });
      closeEdit();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("errors.serverError"));
    } finally {
      setSaving(false);
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

  // ─── Member handlers ───────────────────────────────────────────────────────

  function handleMemberSearchChange(q: string) {
    setMembers((m) => ({ ...m, searchQ: q, selectedUser: null }));
    if (searchTimer.current) clearTimeout(searchTimer.current);
    if (!q.trim()) { setMembers((m) => ({ ...m, searchResults: [], searching: false })); return; }
    searchTimer.current = setTimeout(() => { void runUserSearch(q); }, 350);
  }

  async function runUserSearch(q: string) {
    setMembers((m) => ({ ...m, searching: true }));
    try {
      const result = await adminUsers.list({ page: 1, per_page: 20, search: q });
      const existing = new Set(members.list.map((m) => m.user_id));
      setMembers((m) => ({
        ...m, searching: false,
        searchResults: result.items.filter((u) => !existing.has(u.id)),
      }));
    } catch {
      setMembers((m) => ({ ...m, searching: false, searchResults: [] }));
    }
  }

  function selectUser(u: AdminUserOut) {
    setMembers((m) => ({ ...m, selectedUser: u, searchQ: u.display_name ?? u.ldap_uid, searchResults: [] }));
  }

  async function handleAddMember() {
    if (!editingInst || !members.selectedUser) return;
    setMembers((m) => ({ ...m, adding: true, addError: null }));
    try {
      await adminInstances.addMember(editingInst.id, { user_id: members.selectedUser.id, role: members.addRole });
      setMembers((m) => ({ ...m, adding: false, selectedUser: null, searchQ: "", searchResults: [] }));
      await loadMembers(editingInst.id);
      // Refresh list to update member_count
      const updated = await adminInstances.get(editingInst.id);
      setItems((prev) => prev.map((i) => (i.id === updated.id ? updated : i)));
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : t("errors.serverError");
      setMembers((m) => ({ ...m, adding: false, addError: msg }));
    }
  }

  async function handleRemoveMember(userId: number) {
    if (!editingInst) return;
    try {
      await adminInstances.removeMember(editingInst.id, userId);
      setMembers((m) => ({ ...m, list: m.list.filter((x) => x.user_id !== userId) }));
      const updated = await adminInstances.get(editingInst.id);
      setItems((prev) => prev.map((i) => (i.id === updated.id ? updated : i)));
    } catch (err) {
      setMembers((m) => ({ ...m, error: err instanceof ApiError ? err.message : t("errors.serverError") }));
    }
  }

  async function handleChangeRole(userId: number, role: string) {
    if (!editingInst) return;
    try {
      await adminInstances.addMember(editingInst.id, { user_id: userId, role });
      setMembers((m) => ({
        ...m, list: m.list.map((x) => x.user_id === userId ? { ...x, role } : x),
      }));
    } catch (err) {
      setMembers((m) => ({ ...m, error: err instanceof ApiError ? err.message : t("errors.serverError") }));
    }
  }

  const ef = (field: keyof EditForm) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setEditForm((f) => f ? { ...f, [field]: e.target.value } : f);

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
              <th>Overrides</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {items.map((inst) => (
              <tr key={inst.id}>
                <td>
                  <div className="d-flex align-items-center">
                    <InstanceBadge inst={inst} />
                    <div>
                      <span className="fw-semibold">{inst.name}</span>
                      {inst.description && (
                        <div className="small text-body-secondary">{inst.description}</div>
                      )}
                    </div>
                  </div>
                </td>
                <td><code>{inst.slug}</code></td>
                <td>{inst.member_count}</td>
                <td>{inst.group_count}</td>
                <td>{inst.doc_count}</td>
                <td>
                  {countOverrides(inst.settings) > 0 ? (
                    <span className="badge bg-warning text-dark">
                      {countOverrides(inst.settings)} aktiv
                    </span>
                  ) : (
                    <span className="text-body-secondary small">–</span>
                  )}
                </td>
                <td className="text-end">
                  <div className="d-flex gap-1 justify-content-end">
                    <Button variant="outline-secondary" size="sm" onClick={() => openEdit(inst)}>
                      <i className="bi bi-pencil" />
                    </Button>
                    <Button
                      variant="outline-danger" size="sm"
                      disabled={deletingId === inst.id}
                      onClick={() => void handleDelete(inst)}
                    >
                      {deletingId === inst.id
                        ? <Spinner animation="border" size="sm" />
                        : <i className="bi bi-trash" />}
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}

      {/* ── Create Modal ─────────────────────────────────────────────────────── */}
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
                as="textarea" rows={2}
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

      {/* ── Edit Modal ───────────────────────────────────────────────────────── */}
      <Modal show={!!editingInst} onHide={closeEdit} size="lg">
        {editForm && editingInst && (
          <>
            <Modal.Header closeButton>
              <Modal.Title className="d-flex align-items-center gap-2">
                <InstanceBadge inst={editingInst} />
                {editingInst.name}
                <code className="fs-6 text-body-secondary">{editingInst.slug}</code>
              </Modal.Title>
            </Modal.Header>

            <Modal.Body className="p-0">
              <Tab.Container activeKey={activeTab} onSelect={(k) => setActiveTab(k ?? "settings")}>
                <Nav variant="tabs" className="px-3 pt-2">
                  <Nav.Item>
                    <Nav.Link eventKey="settings"><i className="bi bi-gear me-1" />Einstellungen</Nav.Link>
                  </Nav.Item>
                  <Nav.Item>
                    <Nav.Link eventKey="members">
                      <i className="bi bi-people me-1" />Mitglieder
                      <Badge bg="secondary" className="ms-2">{members.list.length}</Badge>
                    </Nav.Link>
                  </Nav.Item>
                </Nav>

                <Tab.Content className="p-3">
                  {/* ── Settings tab ─────────────────────────────────── */}
                  <Tab.Pane eventKey="settings">
                    <Form id="edit-instance-form" onSubmit={handleSaveEdit}>
                      {/* Icon + Color */}
                      <div className="border rounded p-3 mb-3">
                        <div className="fw-semibold mb-3">Erscheinungsbild</div>
                        <div className="row g-3">
                          <div className="col-sm-5">
                            <Form.Group>
                              <Form.Label className="small">Icon</Form.Label>
                              <Form.Select
                                size="sm"
                                value={editForm.icon}
                                onChange={(e) => setEditForm((f) => f ? { ...f, icon: e.target.value } : f)}
                              >
                                {ICONS.map((ic) => (
                                  <option key={ic.value} value={ic.value}>{ic.label}</option>
                                ))}
                              </Form.Select>
                            </Form.Group>
                          </div>
                          <div className="col-sm-7">
                            <Form.Group>
                              <Form.Label className="small">Farbe</Form.Label>
                              <div className="d-flex flex-wrap gap-1 mb-1">
                                {PALETTE.map((c) => (
                                  <button
                                    key={c} type="button"
                                    onClick={() => setEditForm((f) => f ? { ...f, color: c } : f)}
                                    style={{
                                      width: 22, height: 22, borderRadius: 4, background: c, border: "none",
                                      outline: editForm.color === c ? "2px solid #000" : "none",
                                      outlineOffset: 1, cursor: "pointer",
                                    }}
                                  />
                                ))}
                                <input
                                  type="color"
                                  title="Benutzerdefinierte Farbe"
                                  value={editForm.color}
                                  onChange={(e) => setEditForm((f) => f ? { ...f, color: e.target.value } : f)}
                                  style={{ width: 22, height: 22, padding: 1, border: "1px solid #ccc", borderRadius: 4, cursor: "pointer" }}
                                />
                              </div>
                            </Form.Group>
                          </div>
                          <div className="col-12">
                            <span className="small text-body-secondary me-2">Vorschau:</span>
                            <span
                              className="d-inline-flex align-items-center gap-2 px-2 py-1 rounded"
                              style={{ background: editForm.color, color: "#fff" }}
                            >
                              <i className={`bi ${editForm.icon}`} />
                              <span className="small fw-semibold">{editForm.name || editingInst.name}</span>
                            </span>
                          </div>
                        </div>
                      </div>

                      {/* Base info */}
                      <Form.Group className="mb-3">
                        <Form.Label>{t("common.name")}</Form.Label>
                        <Form.Control value={editForm.name} onChange={ef("name")} required />
                      </Form.Group>
                      <Form.Group className="mb-3">
                        <Form.Label>{t("common.description")}</Form.Label>
                        <Form.Control as="textarea" rows={2} value={editForm.description} onChange={ef("description")} />
                      </Form.Group>

                      {editingInst.settings?.opensearch_analyzer && (
                        <div className="mb-3 d-flex align-items-center gap-2 text-body-secondary small">
                          <i className="bi bi-info-circle" />
                          OpenSearch Analyzer: <code>{String(editingInst.settings.opensearch_analyzer)}</code>
                          <span>(beim Erstellen festgelegt, nicht änderbar)</span>
                        </div>
                      )}

                      {/* LLM Overrides */}
                      <div className="border rounded p-3">
                        <div className="fw-semibold mb-1">Instanz-Overrides</div>
                        <p className="text-body-secondary small mb-3">
                          Leere Felder verwenden die globalen Einstellungen aus Admin → Einstellungen.
                        </p>
                        <div className="row g-3">
                          <div className="col-12">
                            <Form.Group>
                              <Form.Label className="small">LLM-Modell</Form.Label>
                              <Form.Control size="sm" placeholder="(global)" value={editForm.llm_model} onChange={ef("llm_model")} />
                            </Form.Group>
                          </div>
                          <div className="col-sm-6">
                            <Form.Group>
                              <Form.Label className="small">Temperature</Form.Label>
                              <Form.Control size="sm" type="text" inputMode="decimal" placeholder="(global)" value={editForm.llm_temperature} onChange={ef("llm_temperature")} />
                            </Form.Group>
                          </div>
                          <div className="col-sm-6">
                            <Form.Group>
                              <Form.Label className="small">Kontext-Tokens (num_ctx)</Form.Label>
                              <Form.Control size="sm" type="number" min={1024} step={1024} placeholder="(global)" value={editForm.llm_num_ctx} onChange={ef("llm_num_ctx")} />
                            </Form.Group>
                          </div>
                          <div className="col-sm-6">
                            <Form.Group>
                              <Form.Label className="small">hybrid_k (Chunks)</Form.Label>
                              <Form.Control size="sm" type="number" min={1} placeholder="(global)" value={editForm.hybrid_k} onChange={ef("hybrid_k")} />
                            </Form.Group>
                          </div>
                          <div className="col-sm-6">
                            <Form.Group>
                              <Form.Label className="small">Score-Threshold</Form.Label>
                              <Form.Control size="sm" type="text" inputMode="decimal" placeholder="(global)" value={editForm.hybrid_score_threshold} onChange={ef("hybrid_score_threshold")} />
                            </Form.Group>
                          </div>
                          <div className="col-sm-6">
                            <Form.Group>
                              <Form.Label className="small">BM25-Gewicht (0.0–1.0)</Form.Label>
                              <Form.Control
                                size="sm" type="text" inputMode="decimal"
                                placeholder="(global)"
                                value={editForm.hybrid_bm25_weight}
                                onChange={ef("hybrid_bm25_weight")}
                              />
                              {editForm.hybrid_bm25_weight.trim() && !isNaN(parseFloat(editForm.hybrid_bm25_weight.replace(",", "."))) && (
                                <div className="text-body-secondary mt-1" style={{ fontSize: "0.75rem" }}>
                                  kNN-Gewicht: {(1 - parseFloat(editForm.hybrid_bm25_weight.replace(",", "."))).toFixed(2)}
                                </div>
                              )}
                            </Form.Group>
                          </div>
                          <div className="col-12">
                            <InstancePromptField
                              value={editForm.llm_system_prompt}
                              onChange={(v) => setEditForm((f) => f ? { ...f, llm_system_prompt: v } : f)}
                            />
                          </div>
                        </div>
                      </div>
                    </Form>
                  </Tab.Pane>

                  {/* ── Members tab ──────────────────────────────────── */}
                  <Tab.Pane eventKey="members">
                    {members.error && (
                      <Alert variant="danger" dismissible onClose={() => setMembers((m) => ({ ...m, error: null }))}>
                        {members.error}
                      </Alert>
                    )}

                    {/* Add member form */}
                    <div className="border rounded p-3 mb-3">
                      <div className="fw-semibold mb-2 small">Mitglied hinzufügen</div>
                      <div className="d-flex gap-2 flex-wrap align-items-start">
                        <div className="position-relative flex-grow-1" style={{ minWidth: 200 }}>
                          <Form.Control
                            size="sm"
                            placeholder="Benutzer suchen…"
                            value={members.searchQ}
                            onChange={(e) => handleMemberSearchChange(e.target.value)}
                          />
                          {members.searching && (
                            <div className="position-absolute end-0 top-50 translate-middle-y pe-2">
                              <Spinner animation="border" size="sm" />
                            </div>
                          )}
                          {members.searchResults.length > 0 && (
                            <div className="border rounded shadow-sm position-absolute w-100 bg-body" style={{ zIndex: 1050, maxHeight: 180, overflowY: "auto" }}>
                              {members.searchResults.map((u) => (
                                <button
                                  key={u.id} type="button"
                                  className="d-block w-100 text-start px-3 py-2 border-0 bg-transparent small"
                                  onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bs-secondary-bg)")}
                                  onMouseLeave={(e) => (e.currentTarget.style.background = "")}
                                  onClick={() => selectUser(u)}
                                >
                                  <code className="me-2">{u.ldap_uid}</code>
                                  <span className="text-body-secondary">{u.display_name ?? ""}</span>
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                        <Form.Select
                          size="sm"
                          style={{ width: 130, flexShrink: 0 }}
                          value={members.addRole}
                          onChange={(e) => setMembers((m) => ({ ...m, addRole: e.target.value as "viewer" | "manager" }))}
                        >
                          <option value="viewer">Leser</option>
                          <option value="manager">Manager</option>
                        </Form.Select>
                        <Button
                          size="sm" variant="primary"
                          disabled={!members.selectedUser || members.adding}
                          onClick={() => void handleAddMember()}
                        >
                          {members.adding ? <Spinner animation="border" size="sm" /> : <i className="bi bi-plus-lg" />}
                          {" "}Hinzufügen
                        </Button>
                      </div>
                      {members.addError && <div className="text-danger small mt-1">{members.addError}</div>}
                      {members.selectedUser && (
                        <div className="small text-success mt-1">
                          <i className="bi bi-check2 me-1" />
                          Ausgewählt: <strong>{members.selectedUser.display_name ?? members.selectedUser.ldap_uid}</strong>
                          {" "}(<code>{members.selectedUser.ldap_uid}</code>)
                        </div>
                      )}
                    </div>

                    {/* Members table */}
                    {members.loading ? (
                      <div className="text-center py-3"><Spinner animation="border" size="sm" /></div>
                    ) : members.list.length === 0 ? (
                      <p className="text-body-secondary small text-center py-3">Keine direkten Mitgliedschaften</p>
                    ) : (
                      <Table size="sm" hover className="mb-0">
                        <thead>
                          <tr>
                            <th>UID</th>
                            <th>Name</th>
                            <th>Rolle</th>
                            <th />
                          </tr>
                        </thead>
                        <tbody>
                          {members.list.map((m) => (
                            <tr key={m.user_id}>
                              <td><code className="small">{m.ldap_uid}</code></td>
                              <td className="small">{m.display_name ?? "—"}</td>
                              <td>
                                <Form.Select
                                  size="sm"
                                  style={{ width: 120 }}
                                  value={m.role}
                                  onChange={(e) => void handleChangeRole(m.user_id, e.target.value)}
                                >
                                  <option value="viewer">Leser</option>
                                  <option value="manager">Manager</option>
                                </Form.Select>
                              </td>
                              <td className="text-end">
                                <Button
                                  variant="outline-danger" size="sm"
                                  onClick={() => void handleRemoveMember(m.user_id)}
                                  title="Aus Instanz entfernen"
                                >
                                  <i className="bi bi-x-lg" />
                                </Button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </Table>
                    )}
                    <div className="text-body-secondary small mt-2">
                      <i className="bi bi-info-circle me-1" />
                      <strong>Leser</strong> dürfen suchen · <strong>Manager</strong> dürfen Dokumente hochladen und löschen
                    </div>
                  </Tab.Pane>
                </Tab.Content>
              </Tab.Container>
            </Modal.Body>

            <Modal.Footer className="justify-content-between">
              {activeTab === "settings" ? (
                <>
                  <Button
                    variant="outline-warning" size="sm"
                    disabled={saving || countOverrides(editingInst.settings) === 0}
                    onClick={() => void handleClearOverrides()}
                    title="LLM-Overrides zurücksetzen (Icon/Farbe bleiben erhalten)"
                  >
                    <i className="bi bi-x-circle me-1" />Overrides zurücksetzen
                  </Button>
                  <div className="d-flex gap-2">
                    <Button variant="secondary" onClick={closeEdit}>{t("common.cancel")}</Button>
                    <Button type="submit" form="edit-instance-form" disabled={saving}>
                      {saving ? <Spinner animation="border" size="sm" /> : t("common.save")}
                    </Button>
                  </div>
                </>
              ) : (
                <Button variant="secondary" onClick={closeEdit} className="ms-auto">{t("common.close")}</Button>
              )}
            </Modal.Footer>
          </>
        )}
      </Modal>
    </div>
  );
}
