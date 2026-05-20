# infra/redis/

Redis-Konfiguration für den RAG-Stack.

## Verwendung

Redis speichert **Dokument-Metadaten** als JSON-Strings. Es gibt keinen Embedding-Cache.

### Key-Schema

```
doc:{instance_slug}:{sha256_hash}  →  JSON (DocumentMetadata)
```

Beispiel:
```
doc:finanzen:a3f8c1...  →  {"title": "bericht.pdf", "file_size": 204800, "page_count": 12, ...}
```

### Operationen

- **Speichern**: `SET doc:{slug}:{hash} <json>` beim Abschluss der Ingestion
- **Prüfen** (Duplikat-Erkennung): `GET doc:{slug}:{hash}` vor der Verarbeitung
- **Auflisten**: `SCAN` mit Pattern `doc:{slug}:*` + `MGET` (kein `KEYS`)
- **Löschen**: `DEL doc:{slug}:{hash}` beim Löschen eines Dokuments

Die App nutzt eine einzige geteilte Redis-Verbindung (`redis.asyncio`), die im lifespan-Kontext von `app_fastapi.py` geöffnet und beim Shutdown geschlossen wird.

## Konfigurationsdatei (`redis.conf`)

```
maxmemory 512mb
maxmemory-policy allkeys-lru
```

Bei Speicherknappheit werden die am längsten nicht genutzten Keys entfernt (`allkeys-lru`). Da Metadaten-Keys kein TTL haben, ist dies die passende Eviction-Policy.

RDB-Persistenz ist aktiv — Metadaten überleben einen Container-Neustart.

## Monitoring

```bash
# Speichernutzung
docker compose exec redis redis-cli INFO memory

# Alle Dokument-Keys einer Instanz
docker compose exec redis redis-cli KEYS "doc:finanzen:*"

# Anzahl Keys gesamt
docker compose exec redis redis-cli DBSIZE

# Langsame Commands prüfen
docker compose exec redis redis-cli SLOWLOG GET 10
```

## Metadaten manuell löschen

Beim Löschen einer Instanz über die Admin-UI werden alle zugehörigen Redis-Keys **automatisch** bereinigt (`delete_instance()` in `instance_service.py`).

Manuelles Eingreifen ist nur in Ausnahmefällen nötig (z.B. nach direktem Löschen des OpenSearch-Index):

```bash
# Alle Keys einer Instanz löschen
docker compose exec redis redis-cli --scan --pattern "doc:<slug>:*" | xargs docker compose exec -T redis redis-cli DEL

# Komplette Datenbank leeren (alle Instanzen!)
docker compose exec redis redis-cli FLUSHDB
```
