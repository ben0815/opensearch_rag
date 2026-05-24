import { useCallback, useEffect, useState } from "react";
import { Alert, Button, Form, Spinner } from "react-bootstrap";
import { useTranslation } from "react-i18next";
import { adminSettings } from "@/api/client";
import { ApiError } from "@/api/client";
import type { SettingsResponse } from "@/types/api";

export default function AdminSettingsPage() {
  const { t } = useTranslation();
  const [data, setData] = useState<SettingsResponse | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await adminSettings.get();
      setData(resp);
      const initial: Record<string, string> = {};
      for (const s of resp.settings) initial[s.key] = s.value;
      setValues(initial);
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
    setSuccess(false);
    try {
      await adminSettings.patch(values);
      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("errors.serverError"));
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <div className="text-center py-5"><Spinner animation="border" /></div>;

  return (
    <div>
      <div className="d-flex align-items-center justify-content-between mb-4">
        <h4 className="mb-0"><i className="bi bi-sliders me-2" />{t("admin.settings")}</h4>
      </div>

      {error && <Alert variant="danger" dismissible onClose={() => setError(null)}>{error}</Alert>}
      {success && <Alert variant="success">{t("settings.saved")}</Alert>}

      {data && (
        <Form onSubmit={handleSave}>
          <div className="row g-3 mb-4">
            {data.spec.map((spec) => (
              <div key={spec.key} className="col-md-6">
                <Form.Group>
                  <Form.Label>
                    {spec.label}
                    {spec.hint && (
                      <span className="ms-1 text-body-secondary small">({spec.hint})</span>
                    )}
                  </Form.Label>
                  <Form.Control
                    type={spec.type === "number" ? "number" : "text"}
                    inputMode={spec.inputmode as React.HTMLAttributes<HTMLInputElement>["inputMode"]}
                    min={spec.min}
                    max={spec.max}
                    step={spec.step}
                    value={values[spec.key] ?? ""}
                    onChange={(e) =>
                      setValues((v) => ({ ...v, [spec.key]: e.target.value }))
                    }
                  />
                </Form.Group>
              </div>
            ))}
          </div>

          <Button type="submit" disabled={saving}>
            {saving && <Spinner animation="border" size="sm" className="me-2" />}
            {t("common.save")}
          </Button>
        </Form>
      )}

      {data && (
        <div className="mt-4">
          <h6 className="text-body-secondary">Aktive Konfiguration (env-Snapshot)</h6>
          <pre className="bg-body-secondary p-3 rounded small" style={{ maxHeight: 300, overflow: "auto" }}>
            {JSON.stringify(data.config_snapshot, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}
