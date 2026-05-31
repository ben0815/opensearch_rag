# infra/

Docker-Compose-Stack und Infrastrukturkonfiguration.

## Stack starten

```bash
cd infra
docker compose up -d
```

## Services

### opensearch
Vektor-Datenbank für Dokument-Embeddings und BM25-Volltextsuche.

- **Image**: `opensearchproject/opensearch:3.6.0`
- **Port**: 9200 (HTTPS), 9600 (Performance Analyzer)
- **Security Plugin**: aktiviert — HTTPS mit selbstsigniertem Demo-Zertifikat, Basic Auth via `OPENSEARCH_USERNAME/PASSWORD`
- **Memory**: 512 MB Heap (`OPENSEARCH_JAVA_OPTS=-Xms512m -Xmx512m`)
- **Volume**: `opensearch-data` (persistent)

Pro Instanz wird ein eigener Index angelegt: `documents_{slug}`. Die Hybrid-Search-Pipeline (`hybrid-rag-pipeline`) kombiniert BM25 und kNN mit min_max-Normalisierung.

### app
FastAPI-Anwendung (uvicorn).

- **Port**: 8081
- **Build**: `Dockerfile` im Projekt-Root
- **Einstiegspunkt**: `uvicorn app.app_fastapi:app`
- **Volumes**: `../src` → `/app/src` (Live-Code), `./logs`
- **Ollama**: läuft **auf dem Host**, erreichbar via `host.docker.internal:11434`
- **Depends on**: opensearch (healthy), redis (healthy), postgres (healthy)

### redis
Speichert Dokument-Metadaten als JSON-Strings.

- **Image**: `redis:7.2-alpine`
- **Port**: 6379
- **Key-Schema**: `doc:{instance_slug}:{sha256}` → JSON (`DocumentMetadata`)
- **Config**: `redis/redis.conf` (maxmemory 512 MB, allkeys-lru, RDB-Persistenz)
- **Volume**: `redis_data` (persistent)

### caddy _(Profil: `caddy`)_
Reverse-Proxy mit automatischem TLS — nur für den Produktionseinsatz.

- **Image**: `caddy:2-alpine`
- **Ports**: 80 (HTTP / ACME-Challenge), 443 (HTTPS)
- **Config**: `caddy/Caddyfile` (nicht in Git — aus `caddy/Caddyfile.example` kopieren)
- **Volumes**: `caddy_data` (Zertifikate), `caddy_config` (Caddy-interne Konfiguration)
- **Aktivierung**: `docker compose --profile caddy up -d`

Vor dem ersten Start:
```bash
cp infra/caddy/Caddyfile.example infra/caddy/Caddyfile
# Domain im Caddyfile anpassen (oder DOMAIN= in .env setzen)
```

Außerdem in `infra/.env` setzen:
```bash
APP_BIND_HOST=127.0.0.1   # App-Port nicht mehr direkt von außen erreichbar
SECURE_COOKIES=true        # Session- und CSRF-Cookies auf HTTPS-only
DOMAIN=rag.example.com     # Muss auf den Host zeigen (für Let's Encrypt)
# APP_SECRET_KEY muss gesetzt sein — Beispiel:
# python -c "import secrets; print(secrets.token_hex(32))"
APP_SECRET_KEY=<langer_zufälliger_wert>
```

Caddy kommuniziert mit der App intern über `app:8081` im Docker-Netzwerk.

**Wartungsseite:** Ist die App nicht erreichbar (502) oder antwortet nicht rechtzeitig (504), liefert Caddy automatisch eine Wartungsseite mit HTTP 503 aus. Benutzer müssen die Seite nicht manuell neu laden — ein `<meta refresh>` startet nach 60 Sekunden einen automatischen Reload. Der App-eigene Wartungsmodus (503 JSON) wird von Caddy nicht abgefangen.

**Updates und Neustarts:** Caddy gehört zum `caddy`-Profil und wird von `docker compose up -d` (ohne `--profile caddy`) nicht angetastet. Während alle anderen Container neu starten, zeigt Caddy automatisch die Wartungsseite — ohne weiteren Eingriff.

**Nach Änderungen am Caddyfile:**
```bash
docker compose --profile caddy restart caddy
```
`caddy reload` allein reicht nicht: Docker Bind-Mounts für Einzeldateien folgen dem Inode; ein atomares Schreiben erzeugt einen neuen Inode, den der laufende Container erst nach einem Restart sieht.

### postgres
Relationale Datenbank für Anwendungsdaten.

- **Image**: `postgres:16-alpine`
- **Schema**: via Alembic (`alembic upgrade head` läuft automatisch beim App-Start)
- **Datenbank**: `ragdb`, **Benutzer**: `raguser`
- **Volume**: `postgres_data` (persistent)
- **Tabellen**: `users`, `instances`, `instance_members`, `groups`, `group_members`, `group_instance_roles`, `app_settings`, `sessions`, `chat_history`

## Konfiguration

### infra/.env
Einzige Konfigurationsdatei — **nicht in Git**. Vorlage: `infra/.env.example`.

```bash
cp infra/.env.example infra/.env
# Anpassen: POSTGRES_PASSWORD, LDAP_URL, LLM_MODEL, …
```

### Precedence (höchste zuerst)
1. docker-compose `environment:` (aus `infra/.env`)
2. `load_dotenv(..., override=False)` im Python-Code (Fallback für lokale Entwicklung ohne Docker)

## Netzwerk

Alle Services sind im Bridge-Netzwerk `opensearch-network` und erreichbar unter ihrem Service-Namen (`opensearch`, `redis`, `postgres`, `app`). Die App erhält zusätzlich `host.docker.internal` → Host-Gateway für Ollama-Zugriff.

Der App-Port auf dem Host wird über `APP_BIND_HOST` gesteuert (Standard: `0.0.0.0` — alle Interfaces, geeignet für Entwicklung auf einem entfernten Rechner). Im Produktionsbetrieb mit Caddy auf `127.0.0.1` setzen.

## Debugging

```bash
# Status aller Services
docker compose ps

# Logs eines Service
docker compose logs -f app
docker compose logs -f opensearch

# OpenSearch-Index prüfen
curl http://localhost:9200/_cat/indices?v

# Redis-Keys einer Instanz
docker compose exec redis redis-cli KEYS "doc:*"

# PostgreSQL-Verbindung
docker compose exec postgres psql -U raguser -d ragdb
```

## Warum liegt das Dockerfile im Projektwurzelverzeichnis?

Das `Dockerfile` liegt bewusst im Root (eine Ebene über `infra/`), weil der Docker
Build-Context den gesamten `src/`-Baum einschließen muss. Der Build-Context in
`docker-compose.yml` ist auf `..` (Projektwurzel) gesetzt:

```yaml
app:
  build:
    context: ..
    dockerfile: Dockerfile
```

Das Dockerfile kann nicht nach `infra/` verschoben werden, ohne den `COPY`-Befehl
und den Context-Pfad anzupassen — der Quellcode unter `src/` wäre sonst im
Build-Context nicht erreichbar.

## Volumes

| Volume | Inhalt |
|---|---|
| `opensearch-data` | OpenSearch-Shards und Indizes |
| `redis_data` | Redis-RDB-Snapshot (Dokument-Metadaten) |
| `postgres_data` | PostgreSQL-Datenbankdateien |
| `caddy_data` | TLS-Zertifikate (Let's Encrypt) |
| `caddy_config` | Caddy-interne Laufzeitkonfiguration |
