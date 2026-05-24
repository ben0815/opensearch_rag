import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Button, Card, Form, Alert, Spinner } from "react-bootstrap";
import { useTranslation } from "react-i18next";
import { auth } from "@/api/client";
import { user as userApi } from "@/api/client";
import { useAuthStore } from "@/stores/authStore";
import { useInstanceStore } from "@/stores/instanceStore";
import { usePreferencesStore } from "@/stores/preferencesStore";
import { ApiError } from "@/api/client";

export default function LoginPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { user, setUser } = useAuthStore();
  const { setInstances } = useInstanceStore();
  const { setLanguage } = usePreferencesStore();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // Already logged in
  useEffect(() => {
    if (user) navigate("/", { replace: true });
  }, [user, navigate]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const resp = await auth.login({ username, password });
      setUser(resp.user, resp.session_lifetime_hours);
      if (resp.user.preferences?.language) setLanguage(resp.user.preferences.language);
      const instances = await userApi.instances();
      setInstances(instances);
      if (resp.user.default_instance_id) {
        useInstanceStore.getState().setSelectedId(resp.user.default_instance_id);
      }
      navigate("/chat", { replace: true });
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError(t("errors.network"));
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="d-flex vh-100 align-items-center justify-content-center bg-body-secondary">
      <Card style={{ width: 360 }} className="shadow-sm">
        <Card.Body className="p-4">
          <h1 className="h4 mb-4 text-center">{t("auth.loginTitle")}</h1>

          {error && (
            <Alert variant="danger" dismissible onClose={() => setError(null)}>
              {error}
            </Alert>
          )}

          <Form onSubmit={handleSubmit}>
            <Form.Group className="mb-3">
              <Form.Label>{t("auth.username")}</Form.Label>
              <Form.Control
                type="text"
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                autoFocus
              />
            </Form.Group>
            <Form.Group className="mb-4">
              <Form.Label>{t("auth.password")}</Form.Label>
              <Form.Control
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </Form.Group>
            <Button type="submit" className="w-100" disabled={loading}>
              {loading ? (
                <Spinner animation="border" size="sm" className="me-2" />
              ) : null}
              {t("auth.login")}
            </Button>
          </Form>
        </Card.Body>
      </Card>
    </div>
  );
}
