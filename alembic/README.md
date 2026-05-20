# alembic/

Datenbankmigrationen für den RAG-Stack, verwaltet mit [Alembic](https://alembic.sqlalchemy.org/).

## Automatischer Ablauf

Der App-Container führt beim Start automatisch `alembic upgrade head` aus (via `infra/scripts/entrypoint.sh`). Für eine leere Datenbank werden dabei alle Tabellen angelegt. Für eine bereits aktuelle Datenbank ist es ein No-op.

## Verzeichnisstruktur

```
alembic/
├── env.py          # Migrationsumgebung — liest DATABASE_URL aus der Umgebungsvariable,
│                   # nutzt asyncpg (kein zweiter Datenbanktreiber nötig)
├── script.py.mako  # Template für neu generierte Migrations-Skripte
└── versions/       # Chronologisch nummerierte Migrations-Dateien
    └── 20260520_0001_initial_schema.py
```

## Häufige Befehle

```bash
# Aktuellen Migrations-Stand der Datenbank anzeigen
alembic current

# Alle bekannten Migrations anzeigen
alembic history --verbose

# Ausstehende Migrations einspielen (passiert beim App-Start automatisch)
alembic upgrade head

# Eine Migration zurückrollen
alembic downgrade -1

# Datenbank als "aktuell" markieren ohne DDL auszuführen
# (für Datenbanken, die vor Alembic-Einführung per init.sql angelegt wurden)
alembic stamp head

# SQL-Vorschau generieren ohne Ausführung
alembic upgrade --sql head
```

## Neue Migration erstellen

```bash
# 1. SQLAlchemy-Modell in src/app/db/models.py anpassen
# 2. Migration automatisch ableiten (Diff gegen aktuelle DB)
alembic revision --autogenerate -m "kurze_beschreibung"
# 3. Generierte Datei in alembic/versions/ immer manuell prüfen —
#    autogenerate erkennt nicht alles (z.B. CHECK-Constraints, partielle Indizes)
# 4. Beim nächsten Container-Start wird sie automatisch eingespielt
```

## Namenskonvention

Migrations-Dateien folgen dem Muster `YYYYMMDD_<rev>_<slug>.py` (konfiguriert in `alembic.ini`).
Die `revision`-ID ist eine kurze eindeutige Zeichenfolge, die Alembic automatisch generiert.

## Konfiguration

Die Datenbank-URL wird aus der Umgebungsvariable `DATABASE_URL` gelesen (gesetzt in `infra/docker-compose.yml`). Die `sqlalchemy.url` in `alembic.ini` dient nur als Fallback für den Offline-Modus (`alembic upgrade --sql`).
