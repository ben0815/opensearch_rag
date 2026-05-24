# app/

FastAPI-Anwendung. Einstiegspunkt: `app_fastapi.py`.

## Module

### `app_fastapi.py`
FastAPI-App mit `lifespan`-Kontext: initialisiert `LoaderConfig`, Redis-Verbindung, lädt DB-Einstellungen, startet Session- und Audit-Cleanup-Tasks (stündlich bzw. täglich), registriert Middleware und Router.

**Middleware-Stack** (innen → außen):
1. `AuthMiddleware` — Session-Token aus Cookie; API-Pfade ohne gültige Session → 401 JSON; SPA-Pfade ohne Session durchgelassen (AuthGuard im Frontend)
2. `CsrfMiddleware` — Double-Submit-Cookie-Muster (HMAC-SHA256)
3. `SecurityHeadersMiddleware` — CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy

### `ingest.py`
CLI-Tool für Bulk-Ingestion:
```bash
python -m app.ingest --instance <slug> /pfad/zu/pdfs/ [--recursive]
```
Zeigt Live-Fortschrittsbalken pro Datei. Bereits indizierte Dateien werden via SHA-256-Hash übersprungen.

### `rag.py`
Retrieval + Generation:
- `retrieve()` — Hybrid-Search (BM25 + kNN), Deduplizierung, Score-Filter (`HYBRID_SCORE_THRESHOLD`)
- `generate_stream()` — LangChain-Chain mit `OllamaLLM`; nimmt optionale `history`-Liste entgegen (letzte 3 Chat-Einträge als Gesprächskontext)
- `get_llm()` — gecachter LLM-Singleton pro Modell-Key (`num_ctx`, `temperature`, `timeout` konfigurierbar)
- Prompt: `/no_think`-Direktive (unterdrückt Qwen3-Denkblöcke), Deutschgebot, Kontext-strenge Antwortpflicht

### `dependencies.py`
FastAPI-Dependencies: `get_config()`, `get_redis()`, `limiter` (slowapi, Rate Limiting).

---

## auth/

| Datei | Inhalt |
|---|---|
| `ldap_service.py` | Synchroner LDAP-Bind, prüft `pwdAccountLockedTime` und `shadowExpire`, optionaler Admin-Gruppen-Check. Immer via `asyncio.to_thread()` aufrufen. |
| `middleware.py` | `AuthMiddleware`: Session-Token aus Cookie prüfen. API-Pfade ohne gültige Session → 401 JSON. Nicht-API-Pfade werden ohne Auth durchgelassen (React SPA lädt, AuthGuard übernimmt). Verwendet `config_service.is_maintenance_mode()` für Wartungsblock. |
| `session.py` | `create_session()`, `get_user_and_session_by_token()`, `delete_session()`, `purge_expired_sessions()`. Sessions in PostgreSQL, Lifetime über AppSetting `session_lifetime_hours` konfigurierbar. |
| `csrf.py` | `CsrfMiddleware`: Double-Submit-Cookie-Muster mit HMAC-SHA256-Signierung (stdlib). Setzt `csrftoken`-Cookie auf jedem Request. Validiert bei unsafe Methods über `X-CSRF-Token`-Header. `enforce=False` → nur Logging, kein 403. |

## cli/

`admin.py` — Bootstrap-Admin anlegen und Verschlüsselungsschlüssel rotieren:
```bash
python -m app.cli.admin create-admin <username> <passwort>
python -m app.cli.admin rotate-encryption-key <new_key>
python -m app.cli.admin generate-encryption-key
```

## db/

| Datei | Inhalt |
|---|---|
| `models.py` | SQLAlchemy-Modelle: `User`, `Instance`, `InstanceMember`, `Group`, `GroupMember`, `GroupInstanceRole`, `AppSetting`, `ChatHistory`, `Session`, `AuditLog` |
| `session.py` | `AsyncEngine` (pool_size=10), `get_session_factory()`, `get_db()` FastAPI-Dependency |

## loader/

| Datei | Inhalt |
|---|---|
| `config.py` | `LoaderConfig` — liest alle Env-Vars via `os.getenv()` |
| `vector_store.py` | `VectorStore`: OpenSearch-Index + Hybrid-Search-Pipeline; `for_instance()`-Cache (Double-Checked Lock) |
| `document_processor.py` | `DocumentProcessor`: PDF → Chunks → OpenSearch + Redis; `asyncio.Semaphore(3)` für max. 3 parallele Embedding-Calls |
| `chunk_splitter.py` | `ChunkSplitter`: Token-basierter `RecursiveCharacterTextSplitter`, Nachbarkontext, `_truncate_to_tokens()` |
| `exceptions.py` | `LoaderError` |

**Ingestion-Pipeline:**
```
PDF → fitz → Text → split_into_chunks → add_neighbouring_content
    → _embed_chunks (Semaphore 3) → process_chunk → asyncio.to_thread(store.add_texts)
    → RedisMetadataService.save_document_metadata
```

## metadata/

`redis_service.py` — `RedisMetadataService`: speichert `DocumentMetadata` (Pydantic) als JSON in Redis.
Key-Schema: `doc:{instance_slug}:{sha256}`. Listing via SCAN (kein KEYS).

## routes/

| Datei | Routen |
|---|---|
| `auth.py` | `POST /api/auth/login` (Rate: 10/min), `POST /api/auth/logout`, `GET /api/auth/me` |
| `user.py` | `GET /api/instances`, `PATCH /api/users/me` |
| `chat.py` | `POST /api/chat/stream` (SSE), `GET/DELETE /api/chat/history`, `PATCH /api/chat/history/{id}` |
| `documents.py` | `GET /api/documents/{id}`, `POST /api/documents/{id}/upload` (SSE), `DELETE /api/documents/{id}/{hash}` |
| `admin.py` | Alle `/api/admin/*`-Routen (nur Global-Admins): |
| | `GET/POST/PATCH/DELETE /api/admin/instances[/{id}]` |
| | `GET/POST/PATCH/DELETE /api/admin/users[/{id}]`, `POST /api/admin/users/{id}/impersonate` |
| | `GET/POST/DELETE /api/admin/groups[/{id}]` |
| | `GET/PATCH /api/admin/settings` |
| | `GET/PUT /api/admin/ldap`, `POST /api/admin/ldap/test`, `POST /api/admin/ldap/sync` |
| | `GET/POST /api/admin/maintenance` |
| | `GET /api/admin/status` |
| | `GET /api/admin/audit` |

## services/

| Datei | Inhalt |
|---|---|
| `chat_service.py` | `stream_answer(question, slug, config, history)` — synchroner SSE-Generator (via `iterate_in_threadpool`); letzte 3 Chat-Einträge als Gesprächskontext; `save_to_history()` |
| `config_service.py` | `get_effective_config()` — instanzspezifische LLM-Overrides über globaler Config; `get_ldap_config()` mit 30 s TTL-Cache; `is_maintenance_mode()` mit 60 s TTL-Cache; `set_app_setting()`, `save_ldap_config()` |
| `document_service.py` | `get_document_processor()`, `list_documents()`, `delete_document()` |
| `instance_service.py` | `create_instance(analyzer=…)` — wählt BM25-Analyzer pro Instanz; `delete_instance()` (OpenSearch-Index + VectorStore-Cache) |
| `user_service.py` | `get_user_instances()`, `get_effective_role()` — berücksichtigt direkte + Gruppen-Zuweisungen |

## utils/

| Datei | Inhalt |
|---|---|
| `logging_config.py` | `setup_logger()`: strukturiertes Logging mit Modul-Namen |
| `crypto.py` | `encrypt()`/`decrypt()` via Fernet (optional — nur wenn `ENCRYPTION_KEY` gesetzt ist); schützt `ldap_bind_password` in der DB |
