import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Button, Collapse, Form, Spinner } from "react-bootstrap";
import { useTranslation } from "react-i18next";
import { adminSettings } from "@/api/client";
import { ApiError } from "@/api/client";
import type { SettingSpec, SettingsResponse } from "@/types/api";

// ─── System-Prompt constants ──────────────────────────────────────────────────

const DEFAULT_PROMPT = `/no_think Du bist ein präziser Assistent. Beantworte die Frage ausschließlich auf Basis der folgenden Kontext-Abschnitte aus den Dokumenten. Antworte ausschließlich auf Deutsch.

Wenn die Antwort nicht im Kontext enthalten ist, antworte exakt:
"Die gesuchte Information wurde in den verfügbaren Dokumenten nicht gefunden."

Erfinde keine Informationen und ergänze nichts aus eigenem Wissen.
{history}
Kontext:
{context}

Frage: {question}

Antwort:`;

const REQUIRED_PLACEHOLDERS = ["{context}", "{question}", "{history}"] as const;

// ─── Textarea field with prompt-specific UX ───────────────────────────────────

function PromptTextareaField({
  spec,
  value,
  onChange,
}: {
  spec: SettingSpec;
  value: string;
  onChange: (v: string) => void;
}) {
  const [showHelp, setShowHelp] = useState(false);
  const [showDefault, setShowDefault] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const hasContent = value.trim().length > 0;
  const missingPlaceholders = hasContent
    ? REQUIRED_PLACEHOLDERS.filter((p) => !value.includes(p))
    : [];

  function insertPlaceholder(placeholder: string) {
    const el = textareaRef.current;
    if (!el) {
      onChange(value + placeholder);
      return;
    }
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

      {/* ── Label row ──────────────────────────────────────────────────── */}
      <div className="d-flex align-items-center gap-2 mb-2">
        <Form.Label className="mb-0 fw-semibold">{spec.label}</Form.Label>

        {/* (?) help toggle */}
        <button
          type="button"
          onClick={() => setShowHelp((v) => !v)}
          title="Hilfe anzeigen"
          style={{
            width: 20, height: 20, borderRadius: "50%", border: "1.5px solid",
            borderColor: showHelp ? "var(--bs-primary)" : "var(--bs-secondary-color)",
            background: showHelp ? "var(--bs-primary)" : "transparent",
            color: showHelp ? "#fff" : "var(--bs-secondary-color)",
            fontSize: 11, fontWeight: 700, lineHeight: 1,
            cursor: "pointer", flexShrink: 0,
          }}
        >
          ?
        </button>

        <div className="ms-auto d-flex gap-2">
          <Button
            variant="link"
            size="sm"
            className="p-0 text-body-secondary text-decoration-none"
            onClick={() => setShowDefault((v) => !v)}
          >
            <i className={`bi bi-eye${showDefault ? "-slash" : ""} me-1`} />
            {showDefault ? "Standard ausblenden" : "Standard anzeigen"}
          </Button>
          {hasContent && (
            <Button
              variant="outline-danger"
              size="sm"
              onClick={() => onChange("")}
              title="Feld leeren — eingebauter Standard wird wieder verwendet"
            >
              <i className="bi bi-arrow-counterclockwise me-1" />
              Zurücksetzen
            </Button>
          )}
        </div>
      </div>

      {/* ── Always-visible placeholder chips ───────────────────────────── */}
      <div className="d-flex align-items-center flex-wrap gap-1 mb-2 p-2 rounded"
        style={{ background: "var(--bs-tertiary-bg)", border: "1px solid var(--bs-border-color)" }}
      >
        <span className="text-body-secondary small me-1" style={{ whiteSpace: "nowrap" }}>
          Pflicht-Platzhalter:
        </span>
        {REQUIRED_PLACEHOLDERS.map((p) => {
          const missing = hasContent && !value.includes(p);
          return (
            <button
              key={p}
              type="button"
              onClick={() => insertPlaceholder(p)}
              title={missing ? `${p} fehlt — klicken zum Einfügen` : `Klicken um ${p} an Cursor-Position einzufügen`}
              style={{
                fontFamily: "monospace", fontSize: "0.78rem",
                padding: "1px 7px", borderRadius: 4,
                border: `1px solid ${missing ? "var(--bs-danger)" : "var(--bs-secondary-color)"}`,
                background: missing ? "var(--bs-danger-bg-subtle)" : "var(--bs-secondary-bg)",
                color: missing ? "var(--bs-danger-text-emphasis)" : "var(--bs-body-color)",
                cursor: "pointer",
              }}
            >
              {missing && <i className="bi bi-exclamation-triangle-fill me-1" style={{ fontSize: 10 }} />}
              {p}
            </button>
          );
        })}
        <span className="text-body-secondary small ms-1" style={{ fontSize: "0.75rem" }}>
          — alle drei müssen im Prompt enthalten sein · Klicken zum Einfügen
        </span>
      </div>

      {/* ── Collapsible help text ───────────────────────────────────────── */}
      <Collapse in={showHelp}>
        <div>
          <Alert variant="info" className="py-2 px-3 small mb-2">
            <div className="fw-semibold mb-1">
              <i className="bi bi-info-circle me-1" />Was ist der System-Prompt?
            </div>
            <p className="mb-2">
              Der System-Prompt gibt dem LLM seine Rolle vor — er steuert Tonalität,
              Antwortsprache und Verhalten wenn die gesuchte Information nicht in den
              Dokumenten vorhanden ist.
            </p>
            <p className="mb-2">
              <strong>Leer lassen</strong> = eingebauter Standardprompt wird verwendet.
              Kein Neustart nötig — Änderungen gelten sofort für neue Anfragen.
            </p>
            <p className="mb-2">
              <strong>Qwen3-Modelle:</strong> Das Präfix <code>/no_think</code> am Anfang
              des Prompts deaktiviert den internen Thinking-Modus. Ohne dieses Präfix
              werden Antworten deutlich langsamer und beginnen mit langen internen
              Überlegungen — in RAG-Anwendungen meist unerwünscht.
            </p>
            <p className="mb-0">
              <strong>Kontext-Budget:</strong> Der Prompt selbst belegt Tokens im
              LLM-Kontext (num_ctx). Ein sehr langer Prompt reduziert den verfügbaren
              Platz für Dokumentenabschnitte. Der eingebaute Standard belegt ca. 150 Tokens.
            </p>
          </Alert>
        </div>
      </Collapse>

      {/* ── Textarea ────────────────────────────────────────────────────── */}
      <Form.Control
        ref={textareaRef as React.Ref<HTMLTextAreaElement>}
        as="textarea"
        rows={11}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={DEFAULT_PROMPT}
        isInvalid={missingPlaceholders.length > 0}
        style={{ fontFamily: "monospace", fontSize: "0.85rem", resize: "vertical" }}
      />

      {/* ── Live validation feedback ────────────────────────────────────── */}
      {missingPlaceholders.length > 0 && (
        <div className="text-danger small mt-1">
          <i className="bi bi-exclamation-triangle-fill me-1" />
          Fehlende Platzhalter:{" "}
          {missingPlaceholders.map((p) => <code key={p} className="me-1">{p}</code>)}
          — ohne diese Platzhalter kann der Prompt nicht gespeichert werden.
        </div>
      )}

      {/* ── Empty-state hint ────────────────────────────────────────────── */}
      {!hasContent && (
        <div className="text-body-secondary small mt-1">
          <i className="bi bi-info-circle me-1" />
          Kein benutzerdefinierter Prompt gespeichert — eingebauter Standardprompt ist aktiv.{" "}
          <button
            type="button"
            className="btn btn-link btn-sm p-0 text-body-secondary small"
            style={{ verticalAlign: "baseline", textDecoration: "underline dotted" }}
            onClick={() => setShowDefault(true)}
          >
            Standard anzeigen
          </button>
        </div>
      )}

      {/* ── Collapsible default prompt ──────────────────────────────────── */}
      <Collapse in={showDefault}>
        <div>
          <div className="mt-2 rounded border small overflow-hidden">
            <div className="px-3 py-1 fw-semibold text-body-secondary d-flex justify-content-between align-items-center"
              style={{ background: "var(--bs-tertiary-bg)", borderBottom: "1px solid var(--bs-border-color)" }}
            >
              <span><i className="bi bi-code-square me-1" />Eingebauter Standardprompt</span>
              <button
                type="button"
                className="btn btn-link btn-sm p-0 text-body-secondary"
                title="Als Ausgangspunkt übernehmen"
                onClick={() => { onChange(DEFAULT_PROMPT); setShowDefault(false); }}
              >
                <i className="bi bi-clipboard-plus me-1" />Übernehmen
              </button>
            </div>
            <pre
              className="mb-0 px-3 py-2 small"
              style={{ whiteSpace: "pre-wrap", wordBreak: "break-word", fontFamily: "monospace", maxHeight: 260, overflowY: "auto" }}
            >
              {DEFAULT_PROMPT}
            </pre>
          </div>
        </div>
      </Collapse>

    </Form.Group>
  );
}

// ─── Standard field with optional (?) description ────────────────────────────

function StandardField({
  spec,
  value,
  onChange,
  derived,
}: {
  spec: SettingSpec;
  value: string;
  onChange: (v: string) => void;
  derived?: string;
}) {
  const [showDesc, setShowDesc] = useState(false);

  return (
    <Form.Group>
      <div className="d-flex align-items-center gap-1 mb-1">
        <Form.Label className="mb-0">
          {spec.label}
          {spec.hint && (
            <span className="ms-1 text-body-secondary small">({spec.hint})</span>
          )}
        </Form.Label>
        {spec.description && (
          <button
            type="button"
            onClick={() => setShowDesc((v) => !v)}
            title="Erklärung anzeigen"
            style={{
              width: 16, height: 16, borderRadius: "50%", border: "1.5px solid",
              borderColor: showDesc ? "var(--bs-primary)" : "var(--bs-secondary-color)",
              background: showDesc ? "var(--bs-primary)" : "transparent",
              color: showDesc ? "#fff" : "var(--bs-secondary-color)",
              fontSize: 9, fontWeight: 700, lineHeight: 1,
              cursor: "pointer", flexShrink: 0,
            }}
          >
            ?
          </button>
        )}
        {derived && (
          <span className="ms-auto text-body-secondary small">{derived}</span>
        )}
      </div>

      {spec.description && (
        <Collapse in={showDesc}>
          <div>
            <Alert variant="info" className="py-2 px-3 small mb-2">
              {spec.description.split("\n").map((line, i) =>
                line === "" ? <br key={i} /> : <span key={i}>{line}<br /></span>
              )}
            </Alert>
          </div>
        </Collapse>
      )}

      <Form.Control
        type={spec.type === "number" ? "number" : "text"}
        inputMode={spec.inputmode as React.HTMLAttributes<HTMLInputElement>["inputMode"]}
        min={spec.min}
        max={spec.max}
        step={spec.step}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </Form.Group>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

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
            {data.spec.map((spec) => {
              if (spec.type === "textarea") {
                return (
                  <div key={spec.key} className="col-12">
                    <PromptTextareaField
                      spec={spec}
                      value={values[spec.key] ?? ""}
                      onChange={(v) => setValues((prev) => ({ ...prev, [spec.key]: v }))}
                    />
                  </div>
                );
              }
              const bm25Raw = values["hybrid_bm25_weight"]?.replace(",", ".");
              const derived =
                spec.key === "hybrid_bm25_weight" && bm25Raw && !isNaN(parseFloat(bm25Raw))
                  ? `→ kNN-Gewicht: ${(1 - parseFloat(bm25Raw)).toFixed(2)}`
                  : undefined;
              return (
                <div key={spec.key} className="col-md-6">
                  <StandardField
                    spec={spec}
                    value={values[spec.key] ?? ""}
                    onChange={(v) => setValues((prev) => ({ ...prev, [spec.key]: v }))}
                    derived={derived}
                  />
                </div>
              );
            })}
          </div>

          <Button type="submit" disabled={saving}>
            {saving && <Spinner animation="border" size="sm" className="me-2" />}
            {t("common.save")}
          </Button>
        </Form>
      )}

    </div>
  );
}
