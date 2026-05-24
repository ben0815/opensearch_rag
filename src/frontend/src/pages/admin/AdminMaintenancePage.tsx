import { useCallback, useEffect, useState } from "react";
import { Alert, Button, Card, Spinner } from "react-bootstrap";
import { useTranslation } from "react-i18next";
import { adminMaintenance } from "@/api/client";
import { ApiError } from "@/api/client";

export default function AdminMaintenancePage() {
  const { t } = useTranslation();
  const [active, setActive] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await adminMaintenance.status();
      setActive(resp.maintenance_mode);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("errors.serverError"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { void load(); }, [load]);

  async function handleToggle() {
    setSaving(true);
    setError(null);
    try {
      await adminMaintenance.set(!active);
      setActive((a) => !a);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("errors.serverError"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <h4 className="mb-4"><i className="bi bi-tools me-2" />{t("admin.maintenance")}</h4>

      {error && <Alert variant="danger" dismissible onClose={() => setError(null)}>{error}</Alert>}

      {loading ? (
        <Spinner animation="border" />
      ) : (
        <Card style={{ maxWidth: 480 }} className={`border-${active ? "warning" : "secondary"}`}>
          <Card.Body>
            <Card.Title>
              {active ? (
                <><i className="bi bi-exclamation-triangle-fill text-warning me-2" />Wartungsmodus aktiv</>
              ) : (
                <><i className="bi bi-check-circle text-success me-2" />Normalbetrieb</>
              )}
            </Card.Title>
            <Card.Text className="text-body-secondary">
              {t("admin.maintenanceHint")}
            </Card.Text>
            <Button
              variant={active ? "warning" : "outline-warning"}
              onClick={handleToggle}
              disabled={saving}
            >
              {saving && <Spinner animation="border" size="sm" className="me-2" />}
              {active ? t("admin.maintenanceOff") : t("admin.maintenanceOn")}
            </Button>
          </Card.Body>
        </Card>
      )}
    </div>
  );
}
