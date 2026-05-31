"""Gemeinsame Helpers für alle Admin-Sub-Router."""
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, User
from app.db.session import get_db


_PAGE_SIZE_USERS = 25
_PAGE_SIZE_GROUPS = 10
_PAGE_SIZE_AUDIT = 50

_SYSTEM_PROMPT_DESCRIPTION = (
    "Der Prompt steuert Tonalität, Sprache und Verhalten des LLM.\n\n"
    "Pflicht-Platzhalter (müssen enthalten sein):\n"
    "  {context}  — gefundene Dokumentenabschnitte\n"
    "  {question} — Frage des Benutzers\n"
    "  {history}  — bisheriger Gesprächsverlauf\n\n"
    "Fehlt ein Platzhalter, wird beim Speichern ein Fehler gemeldet.\n\n"
    "Hinweis für Qwen3-Modelle: /no_think am Anfang des Prompts deaktiviert "
    "den internen Thinking-Modus. Ohne dieses Präfix werden Antworten deutlich "
    "langsamer und beginnen mit langen internen Überlegungen.\n\n"
    "Kontext-Budget: Der Prompt selbst belegt Tokens im LLM-Kontext (num_ctx). "
    "Ein sehr langer Prompt reduziert den verfügbaren Platz für Dokumentenabschnitte.\n\n"
    "Leer lassen = eingebauter Standardprompt wird verwendet."
)

_SETTINGS_SPEC: list[dict] = [
    {
        "key": "llm_model", "label": "LLM-Modell", "type": "text",
        "inputmode": None, "min": None, "max": None, "step": None,
        "hint": "Muss in Ollama gepullt sein", "description": None,
    },
    {
        "key": "llm_temperature", "label": "Temperature", "type": "text",
        "inputmode": "decimal", "min": 0.0, "max": 2.0, "step": 0.1,
        "hint": "0.0 = deterministisch, 2.0 = kreativ", "description": None,
    },
    {
        "key": "llm_num_ctx", "label": "Kontext-Tokens (num_ctx)", "type": "number",
        "inputmode": None, "min": 1024, "max": 131072, "step": 1024,
        "hint": "Kontextfenster für Ollama",
        "description": (
            "Wie viele Tokens das LLM gleichzeitig im Blick behalten kann. "
            "Das Fenster enthält: System-Prompt (~150 T) + Gesprächsverlauf (~500 T) "
            "+ gefundene Dokumenten-Chunks (~6.000 T bei 10 Chunks) + Frage (~50 T).\n\n"
            "Standard 16.384 bietet ausreichend Puffer für die Standardkonfiguration. "
            "Erhöhen wenn das LLM Antworten abschneidet oder Kontext verliert. "
            "Senken wenn der GPU-VRAM knapp wird — jeder Token kostet ca. 0,5–2 MB VRAM."
        ),
    },
    {
        "key": "llm_timeout_seconds", "label": "LLM-Timeout (s)", "type": "number",
        "inputmode": None, "min": 10, "max": 600, "step": 10,
        "hint": "Max. Wartezeit auf LLM-Antwort", "description": None,
    },
    {
        "key": "llm_system_prompt", "label": "System-Prompt (LLM)", "type": "textarea",
        "inputmode": None, "min": None, "max": None, "step": None,
        "hint": None, "description": _SYSTEM_PROMPT_DESCRIPTION,
    },
    {
        "key": "hybrid_bm25_weight", "label": "BM25-Gewicht", "type": "text",
        "inputmode": "decimal", "min": 0.0, "max": 1.0, "step": 0.05,
        "hint": "kNN-Gewicht = 1.0 − BM25",
        "description": (
            "Die Suche kombiniert zwei Verfahren: BM25 (Volltextsuche — findet exakte Wörter) "
            "und kNN (Vektorsuche — findet ähnliche Bedeutungen). Dieses Gewicht steuert das Verhältnis.\n\n"
            "Empfehlungen:\n"
            "• 0.3 / kNN 0.7 — allgemeine Texte, Berichte, freier Wortschatz\n"
            "• 0.4 / kNN 0.6 — Standard, gute Balance (Voreinstellung)\n"
            "• 0.5 / kNN 0.5 — technische Handbücher, Gesetze, Fachbegriffe sind kritisch\n\n"
            "Das kNN-Gewicht wird automatisch als 1.0 − BM25-Gewicht berechnet."
        ),
    },
    {
        "key": "hybrid_k", "label": "Anzahl Treffer (hybrid_k)", "type": "number",
        "inputmode": None, "min": 1, "max": 100, "step": 1,
        "hint": "Dokumenten-Chunks pro Anfrage",
        "description": (
            "Wie viele Dokumentenabschnitte (Chunks) pro Suchanfrage an das LLM übergeben werden.\n\n"
            "• Zu wenig (< 5): Relevante Stellen können fehlen, besonders bei breiten Fragen.\n"
            "• Zu viel (> 20): Das LLM bekommt mehr Kontext, aber irrelevante Abschnitte "
            "können die Antwort verwässern — und es werden mehr Tokens im Kontextfenster verbraucht.\n\n"
            "Standard 10 ist ein guter Ausgangspunkt. Bei sehr spezifischen Fragen genügen 5–7, "
            "bei Zusammenfassungsaufgaben können 15–20 sinnvoll sein."
        ),
    },
    {
        "key": "hybrid_score_threshold", "label": "Score-Schwelle", "type": "text",
        "inputmode": "decimal", "min": 0.0, "max": 1.0, "step": 0.01,
        "hint": "Mindest-Relevanz (0.0 = deaktiviert)",
        "description": (
            "Chunks mit einem Relevanz-Score unter diesem Wert werden verworfen, "
            "bevor sie ans LLM übergeben werden.\n\n"
            "• 0.0 — deaktiviert, alle Treffer werden verwendet\n"
            "• 0.05–0.1 — Standard, filtert nur klar irrelevante Treffer\n"
            "• 0.15–0.25 — streng, für homogene Dokumentensammlungen\n\n"
            "Symptom für zu hohen Wert: LLM antwortet häufig 'Information nicht gefunden', "
            "obwohl passende Dokumente vorhanden sind → Wert senken.\n"
            "Symptom für zu niedrigen Wert: LLM zieht thematisch falsche Stellen heran → Wert erhöhen."
        ),
    },
    {
        "key": "session_lifetime_hours", "label": "Session-Dauer (h)", "type": "number",
        "inputmode": None, "min": 1, "max": 720, "step": 1,
        "hint": "Standard: 8h", "description": None,
    },
    {
        "key": "max_upload_mb", "label": "Max. Upload-Größe (MB)", "type": "number",
        "inputmode": None, "min": 1, "max": 500, "step": 1,
        "hint": "Standard: 50 MB", "description": None,
    },
    {
        "key": "maintenance_mode", "label": "Wartungsmodus", "type": "text",
        "inputmode": None, "min": None, "max": None, "step": None,
        "hint": "true | false",
        "description": (
            "Gültige Werte: true oder false.\n\n"
            "Im Wartungsmodus erhalten alle Nicht-Admins einen HTTP 503 auf alle Anfragen. "
            "Admins können weiterhin auf die Oberfläche zugreifen.\n\n"
            "Der Wartungsmodus kann bequemer über die Seite 'Wartung' in der Navigation "
            "ein- und ausgeschaltet werden."
        ),
    },
    {
        "key": "audit_retention_days", "label": "Audit-Retention (Tage)", "type": "number",
        "inputmode": None, "min": 7, "max": 3650, "step": 1,
        "hint": "Standard: 90 Tage", "description": None,
    },
    {
        "key": "presence_enabled", "label": "Präsenzanzeige", "type": "text",
        "inputmode": None, "min": None, "max": None, "step": None,
        "hint": "true | false",
        "description": (
            "Zeigt angemeldete Benutzer in der Sidebar an.\n\n"
            "true  = Feature aktiv\n"
            "false = Feature deaktiviert, Sidebar zeigt keine Präsenzliste\n\n"
            "Leer lassen = aktiv (Standard) — kein Eintrag nötig um das Feature zu aktivieren."
        ),
    },
]

_CASTMAP: dict[str, type] = {
    "llm_model": str, "llm_temperature": float, "llm_num_ctx": int,
    "llm_timeout_seconds": int, "llm_system_prompt": str,
    "hybrid_bm25_weight": float, "hybrid_k": int, "hybrid_score_threshold": float,
    "session_lifetime_hours": int, "max_upload_mb": int,
    "maintenance_mode": str, "audit_retention_days": int, "presence_enabled": str,
}


def _require_admin(request: Request) -> User:
    user = getattr(request.state, "user", None)
    if not user or not user.is_global_admin:
        raise HTTPException(status_code=403, detail="Kein Zugriff")
    return user


def _like(q: str) -> str:
    parts = q.split("*")
    escaped = [p.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") for p in parts]
    return "%" + "%".join(escaped) + "%"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _audit(db, user_id, action, target_type=None, target_id=None, detail=None, ip_address=None):
    db.add(AuditLog(
        user_id=user_id,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        detail=detail,
        ip_address=ip_address,
    ))
