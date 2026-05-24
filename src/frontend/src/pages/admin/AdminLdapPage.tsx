import { useCallback, useEffect, useState } from "react";
import { Alert, Badge, Button, Form, Spinner } from "react-bootstrap";
import { useTranslation } from "react-i18next";
import { adminLdap } from "@/api/client";
import { ApiError } from "@/api/client";
import type { LDAPConfigOut } from "@/types/api";

export default function AdminLdapPage() {
  const { t } = useTranslation();
  const [data, setData] = useState<LDAPConfigOut | null>(null);
  const [form, setForm] = useState<Record<string, string | boolean>>({});
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<{ ok: boolean; error: string | null } | null>(null);
  const [syncResult, setSyncResult] = useState<{ synced: number; errors: number } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const cfg = await adminLdap.get();
      setData(cfg);
      setForm({
        ldap_url: cfg.ldap_url,
        ldap_user_search_base: cfg.ldap_user_search_base,
        ldap_uid_attr: cfg.ldap_uid_attr,
        ldap_display_name_attr: cfg.ldap_display_name_attr,
        ldap_mail_attr: cfg.ldap_mail_attr,
        ldap_user_filter: cfg.ldap_user_filter,
        ldap_admin_group_dn: cfg.ldap_admin_group_dn,
        ldap_bind_dn: cfg.ldap_bind_dn,
        ldap_bind_password: "",
        ldap_enabled: cfg.ldap_enabled,
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("errors.serverError"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { void load(); }, [load]);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const payload = { ...form };
      if (!payload.ldap_bind_password) delete payload.ldap_bind_password;
      await adminLdap.save(payload as unknown as Parameters<typeof adminLdap.save>[0]);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("errors.serverError"));
    } finally {
      setSaving(false);
    }
  }

  async function handleTest() {
    setTesting(true);
    setTestResult(null);
    try {
      setTestResult(await adminLdap.test());
    } finally {
      setTesting(false);
    }
  }

  async function handleSync() {
    setSyncing(true);
    setSyncResult(null);
    try {
      setSyncResult(await adminLdap.sync());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("errors.serverError"));
    } finally {
      setSyncing(false);
    }
  }

  function field(key: string, label: string, type = "text", placeholder = "") {
    return (
      <Form.Group className="mb-3" key={key}>
        <Form.Label>{label}</Form.Label>
        <Form.Control
          type={type}
          placeholder={placeholder}
          value={String(form[key] ?? "")}
          onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
        />
      </Form.Group>
    );
  }

  if (loading) return <div className="text-center py-5"><Spinner animation="border" /></div>;

  return (
    <div>
      <div className="d-flex align-items-center justify-content-between mb-4">
        <h4 className="mb-0"><i className="bi bi-shield-lock me-2" />{t("admin.ldap")}</h4>
        <div className="d-flex gap-2">
          <Button variant="outline-secondary" size="sm" onClick={handleTest} disabled={testing}>
            {testing ? <Spinner animation="border" size="sm" /> : <i className="bi bi-plug" />}
            {" "}Test
          </Button>
          <Button variant="outline-primary" size="sm" onClick={handleSync} disabled={syncing}>
            {syncing ? <Spinner animation="border" size="sm" /> : <i className="bi bi-arrow-repeat" />}
            {" "}Sync
          </Button>
        </div>
      </div>

      {error && <Alert variant="danger" dismissible onClose={() => setError(null)}>{error}</Alert>}

      {testResult && (
        <Alert variant={testResult.ok ? "success" : "danger"} dismissible onClose={() => setTestResult(null)}>
          {testResult.ok ? "Verbindung erfolgreich" : `Fehler: ${testResult.error}`}
        </Alert>
      )}

      {syncResult && (
        <Alert variant="info" dismissible onClose={() => setSyncResult(null)}>
          Sync: {syncResult.synced} Benutzer synchronisiert, {syncResult.errors} Fehler
        </Alert>
      )}

      <Form onSubmit={handleSave}>
        <Form.Check
          type="switch"
          label="LDAP aktiviert"
          checked={Boolean(form.ldap_enabled)}
          onChange={(e) => setForm((f) => ({ ...f, ldap_enabled: e.target.checked }))}
          className="mb-3"
        />
        {field("ldap_url", "LDAP URL", "text", "ldap://ldap.example.com:389")}
        {field("ldap_user_search_base", "User Search Base", "text", "ou=users,dc=example,dc=com")}
        {field("ldap_uid_attr", "UID Attribut")}
        {field("ldap_display_name_attr", "Anzeigename Attribut")}
        {field("ldap_mail_attr", "E-Mail Attribut")}
        {field("ldap_user_filter", "User Filter")}
        {field("ldap_admin_group_dn", "Admin Group DN")}
        {field("ldap_bind_dn", "Bind DN")}
        <Form.Group className="mb-3">
          <Form.Label>
            Bind Passwort{" "}
            {data?.ldap_bind_password_set && (
              <Badge bg="secondary-subtle" text="secondary" className="ms-1">gesetzt</Badge>
            )}
          </Form.Label>
          <Form.Control
            type="password"
            placeholder="Leer lassen um nicht zu ändern"
            value={String(form.ldap_bind_password ?? "")}
            onChange={(e) => setForm((f) => ({ ...f, ldap_bind_password: e.target.value }))}
          />
        </Form.Group>

        <Button type="submit" disabled={saving}>
          {saving && <Spinner animation="border" size="sm" className="me-2" />}
          {t("common.save")}
        </Button>
      </Form>
    </div>
  );
}
