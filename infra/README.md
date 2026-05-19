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
- **Port**: 9200 (HTTP), 9600 (Performance Analyzer)
- **Security Plugin**: deaktiviert (`DISABLE_SECURITY_PLUGIN=true`) — internes Deployment
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

### postgres
Relationale Datenbank für Anwendungsdaten.

- **Image**: `postgres:16-alpine`
- **Initialisierung**: `postgres/init.sql`
- **Datenbank**: `ragdb`, **Benutzer**: `raguser`
- **Volume**: `postgres_data` (persistent)
- **Tabellen**: `users`, `instances`, `instance_members`, `groups`, `group_members`, `group_instance_roles`, `sessions`, `chat_history`

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

## Volumes

| Volume | Inhalt |
|---|---|
| `opensearch-data` | OpenSearch-Shards und Indizes |
| `redis_data` | Redis-RDB-Snapshot (Dokument-Metadaten) |
| `postgres_data` | PostgreSQL-Datenbankdateien |
