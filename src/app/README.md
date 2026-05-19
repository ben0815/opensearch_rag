# app/

FastAPI-Anwendung. Einstiegspunkt: `app_fastapi.py`.

## Module

### `app_fastapi.py`
FastAPI-App mit `lifespan`-Kontext: initialisiert `LoaderConfig` und Redis-Verbindung, startet den Session-Cleanup-Task (stündlich), registriert Middleware und Router.

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
| `middleware.py` | `AuthMiddleware`: Session-Token aus Cookie prüfen; nicht authentifizierte Requests → Redirect `/login`. |
| `session.py` | `create_session()`, `get_user_by_token()`, `delete_session()`, `purge_expired_sessions()`. Sessions in PostgreSQL, Lifetime konfigurierbar via `SESSION_LIFETIME_HOURS`. |

## cli/

`admin.py` — Bootstrap-Admin anlegen:
```bash
python -m app.cli.admin create-admin <username> <passwort>
```
Legt einen Benutzer mit lokalem bcrypt-Hash an (kein LDAP erforderlich).

## db/

| Datei | Inhalt |
|---|---|
| `models.py` | SQLAlchemy-Modelle: `User`, `Instance`, `InstanceMember`, `Group`, `GroupMember`, `GroupInstanceRole`, `ChatHistory`, `Session` |
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
| `auth.py` | `GET/POST /login`, `GET /logout` — Rate Limit: 10 Logins/Minute |
| `chat.py` | `GET /chat`, `POST /chat/stream` (SSE), `GET /chat/history`, `POST /chat/save-history`, `POST /chat/history/clear`, `POST /chat/history/{id}/delete` |
| `documents.py` | `GET /documents`, `POST /documents/upload` (SSE), `POST /documents/delete/{hash}` |
| `admin.py` | `/admin/instances`, `/admin/groups`, `/admin/users` + alle CRUD-Unterrouten |

## services/

| Datei | Inhalt |
|---|---|
| `chat_service.py` | `stream_answer(question, slug, config, history)` — synchroner SSE-Generator (läuft via `iterate_in_threadpool`); übergibt letzte 3 Chat-Einträge als Gesprächskontext; `save_to_history()` |
| `document_service.py` | `get_document_processor()`, `list_documents()`, `delete_document()` |
| `instance_service.py` | `create_instance()`, `delete_instance()` (OpenSearch-Index + VectorStore-Cache) |
| `user_service.py` | `get_user_instances()`, `get_effective_role()` — berücksichtigt direkte + Gruppen-Zuweisungen |

## utils/

`logging_config.py` — `setup_logger()`: strukturiertes Logging mit Modul-Namen.
