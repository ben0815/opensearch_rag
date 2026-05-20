# infra/postgres/

PostgreSQL-Konfiguration für den RAG-Stack.

## Schema

Das Datenbankschema wird ausschließlich über **Alembic** verwaltet. Der App-Container führt beim Start automatisch `alembic upgrade head` aus — bei einer leeren Datenbank werden alle Tabellen angelegt, bei einer aktuellen Datenbank ist es ein No-op.

`init.sql` dient nur noch als Referenzdokument und wird nicht mehr in PostgreSQL eingebunden.

### Tabellen

| Tabelle | Inhalt |
|---|---|
| `users` | Alle bekannten Benutzer. Wird beim LDAP-Login automatisch angelegt/aktualisiert. `local_password_hash` nur für Bootstrap-Admin (bcrypt). `is_active` steuert Login-Zugriff. |
| `instances` | Dokumentsammlungen. Jede Instanz hat einen eindeutigen `slug`, der den OpenSearch-Index (`documents_{slug}`) und Redis-Keys (`doc:{slug}:*`) identifiziert. `settings` (JSONB) speichert instanzspezifische Overrides (BM25-Analyzer, LLM-Parameter). |
| `instance_members` | Direkte Benutzer-Instanz-Zuweisungen mit Rolle (`viewer`/`manager`). Composite PK `(user_id, instance_id)`. |
| `groups` | Benutzergruppen, optional mit LDAP-Gruppen-DN verknüpft. Name ist UNIQUE. |
| `group_instance_roles` | Instanz-Zuweisungen für Gruppen mit Rolle. Composite PK `(group_id, instance_id)`. |
| `group_members` | Mitgliedschaft eines Benutzers in einer Gruppe. Composite PK `(user_id, group_id)`. |
| `app_settings` | Globale Admin-Einstellungen (LLM-Modell, Temperature, Suche-Gewichte u.a.), die über die Admin-UI gesetzt werden und `.env`-Defaults überschreiben. PK = `key`. |
| `chat_history` | Gespeicherte Chat-Einträge mit Frage, Antwort und Quell-Chunks als JSONB. |
| `sessions` | Aktive Login-Sessions. Token = zufälliger 32-Byte-urlsafe-String. Abgelaufene Sessions werden stündlich bereinigt. |

### Beziehungen

```
users ──┬── instance_members ── instances
        ├── group_members ────── groups ── group_instance_roles ── instances
        ├── chat_history ─────── instances
        ├── sessions
        └── app_settings (updated_by → users)
```

Alle Fremdschlüssel auf `users` und `instances` sind mit `ON DELETE CASCADE` definiert — ein gelöschter Benutzer oder eine gelöschte Instanz zieht alle abhängigen Zeilen mit.

### Indizes

| Index | Tabelle | Zweck |
|---|---|---|
| `idx_sessions_user_id` | `sessions` | Alle Sessions eines Benutzers finden (z. B. beim Logout) |
| `idx_sessions_expires` | `sessions` | Effizientes Löschen abgelaufener Sessions (`purge_expired_sessions`) |
| `idx_chat_history_user` | `chat_history` | Chat-Verlauf eines Benutzers laden |
| `idx_chat_history_inst` | `chat_history` | Chat-Verlauf nach Instanz filtern |
| `idx_chat_history_time` | `chat_history` | Sortierung nach Datum (DESC) |

## Rollen-Logik

Eine effektive Rolle ergibt sich aus dem Maximum über direkte Zuweisung und alle Gruppen-Zuweisungen: `manager` schlägt `viewer`. Global-Admins haben auf alle Instanzen implizit `manager`-Zugriff (kein Eintrag in `instance_members` erforderlich).

## Debugging

```bash
# Verbindung zur Datenbank
docker compose exec postgres psql -U raguser -d ragdb

# Tabellenübersicht
\dt

# Alle Benutzer
SELECT id, ldap_uid, display_name, is_global_admin, last_login FROM users;

# Instanzen und ihre Mitglieder
SELECT i.name, u.ldap_uid, im.role
FROM instance_members im
JOIN instances i ON i.id = im.instance_id
JOIN users u ON u.id = im.user_id
ORDER BY i.name, im.role;

# Aktive Sessions
SELECT u.ldap_uid, s.expires_at
FROM sessions s
JOIN users u ON u.id = s.user_id
WHERE s.expires_at > NOW();

# Abgelaufene Sessions manuell löschen
DELETE FROM sessions WHERE expires_at <= NOW();
```

## Backup / Restore

```bash
# Backup
docker compose exec postgres pg_dump -U raguser ragdb > ragdb_backup.sql

# Restore
docker compose exec -T postgres psql -U raguser ragdb < ragdb_backup.sql
```
