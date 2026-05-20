# CLAUDE.md — Projektkontext für Claude Code

## Was das Projekt macht

Multi-Tenant RAG-Anwendung (Retrieval-Augmented Generation): PDFs werden in Chunks zerlegt, mit einem lokalen Ollama-Modell eingebettet und in OpenSearch gespeichert. Benutzer authentifizieren sich via LDAP, sind Instanzen (Dokumentsammlungen) zugewiesen und können über eine Web-UI Fragen stellen. Admins verwalten Instanzen, Gruppen und Benutzer. Redis speichert Dokument-Metadaten, PostgreSQL speichert Benutzer, Gruppen, Instanzen und Chat-History.

## Laufzeitumgebung

Alle Dienste laufen in Docker Compose. Der Stack wird aus `infra/` gestartet:

```bash
cd infra
docker compose up -d
```

- App: http://localhost:8081
- OpenSearch: http://localhost:9200
- Ollama läuft **lokal auf dem Host** (nicht im Container), erreichbar über `host.docker.internal:11434`

## Konfigurationsfluss — Single Source of Truth

```
infra/.env  ──►  docker-compose ${VAR:-default}  ──►  Container-Env  ──►  os.getenv() in LoaderConfig
                                                                                        ▲
                                                              load_dotenv(infra/.env, override=False)
                                                              (nur lokal ohne Docker; im Container kein Effekt,
                                                               da alle Vars bereits in der Container-Env gesetzt)
```

**Regeln:**
- Alle Variablen **einmalig** in `infra/.env` setzen — niemals direkt im Code hartkodieren
- `infra/.env.example` ist die vollständige Referenz aller Variablen mit Beschreibung
- `infra/.env` ist in `.gitignore` — **niemals committen**
- `load_dotenv(_env_file, override=False)` in `app_fastapi.py` und `ingest.py` greift nur bei lokaler Entwicklung ohne Docker; im Container sind alle Vars bereits über docker-compose gesetzt

## Kritische Constraint: Embedding-Dimension

`bge-m3` erzeugt **1024-dimensionale** Vektoren. Diese Zahl muss an drei Stellen konsistent sein:
1. `EMBEDDING_SIZE=1024` in `infra/.env`
2. `int(os.getenv('EMBEDDING_SIZE', '1024'))` in `config.py` (Default bereits korrekt)
3. OpenSearch-Index-Mapping in `vector_store.py` → `embedding_dimension = self.config.embedding_size`

Wenn ein Index mit falscher Dimension erstellt wurde, muss er manuell gelöscht werden:
```bash
curl -X DELETE http://localhost:9200/documents_<slug>
```

## Projektstruktur

```
opensearch_rag/
├── Dockerfile                        # Multi-stage build; CMD uvicorn app.app_fastapi:app
├── requirements.txt                  # Pinned third-party deps
├── setup.py                          # Package-Installation (src/ als package root)
├── infra/
│   ├── docker-compose.yml            # 4 Services: opensearch, app, redis, postgres
│   ├── .env                          # Lokale Konfiguration (nicht in Git)
│   ├── .env.example                  # Vorlage mit allen Variablen und Kommentaren
│   ├── redis/redis.conf              # Redis-Persistenz- und Memory-Konfiguration
│   ├── postgres/init.sql             # Referenzdokument (nicht mehr aktiv eingebunden)
│   └── scripts/entrypoint.sh        # Führt alembic upgrade head aus, dann uvicorn
├── alembic.ini                       # Alembic-Konfiguration (script_location, sqlalchemy.url)
└── alembic/
    ├── env.py                        # Async-Migrationsumgebung (liest DATABASE_URL aus Env)
    ├── script.py.mako                # Template für neue Migrations
    └── versions/                     # Migrations-Skripte (chronologisch nummeriert)
└── src/app/
    ├── app_fastapi.py                # Einstiegspunkt: FastAPI-App mit lifespan, Middleware, Router
    ├── ingest.py                     # CLI-Tool: python -m app.ingest --instance <slug> <pdfs>
    ├── rag.py                        # retrieve() + generate_stream(): Hybrid-Search + LLM-Chain
    ├── dependencies.py               # FastAPI-Abhängigkeiten: get_config(), get_redis(), limiter (slowapi)
    ├── auth/
    │   ├── ldap_service.py           # LDAP-Authentifizierung (synchron — in asyncio.to_thread aufrufen)
    │   ├── middleware.py             # AuthMiddleware: Session-Token aus Cookie prüfen
    │   └── session.py               # create_session(), get_user_by_token(), purge_expired_sessions()
    ├── cli/
    │   └── admin.py                  # CLI: python -m app.cli.admin create-admin <user> <pass>
    ├── db/
    │   ├── models.py                 # SQLAlchemy-Modelle: User, Instance, Group, ChatHistory, Session
    │   └── session.py               # AsyncEngine + get_session_factory()
    ├── loader/
    │   ├── config.py                 # LoaderConfig: liest alle Env-Vars via os.getenv()
    │   ├── vector_store.py           # VectorStore: OpenSearch-Index + for_instance()-Cache
    │   ├── document_processor.py     # DocumentProcessor: PDF → Chunks → OpenSearch + Redis
    │   ├── chunk_splitter.py         # ChunkSplitter: RecursiveCharacterTextSplitter + Nachbarkontext
    │   └── exceptions.py            # LoaderError
    ├── metadata/
    │   └── redis_service.py          # RedisMetadataService: speichert DocumentMetadata als JSON
    ├── routes/
    │   ├── auth.py                   # /login, /logout
    │   ├── chat.py                   # /chat, /chat/stream (SSE), /chat/history
    │   ├── documents.py              # /documents, /documents/upload (SSE), /documents/delete/{hash}
    │   └── admin.py                  # /admin/instances, /admin/groups, /admin/users
    ├── services/
    │   ├── chat_service.py           # stream_answer(question, slug, config, history) (SSE-Generator), save_to_history()
    │   ├── document_service.py       # get_document_processor(), list_documents(), delete_document()
    │   ├── instance_service.py       # create_instance(), delete_instance() (inkl. OpenSearch-Index)
    │   └── user_service.py           # get_user_instances(), get_effective_role()
    └── utils/
        └── logging_config.py         # setup_logger(): strukturiertes Logging
```

## Architektur-Entscheidungen

### Multi-Tenant: Instanzen und Rollen
Jede Instanz hat einen eindeutigen `slug` (z.B. `finanzen`). Dokumente werden in einem instanzspezifischen OpenSearch-Index (`documents_<slug>`) gespeichert. Benutzer erhalten Zugriff über direkte `InstanceMember`-Einträge oder über Gruppen (`GroupInstanceRole`). Rollen: `viewer` (Chat) und `manager` (Upload/Löschen). Global-Admins haben automatisch `manager`-Zugriff auf alle Instanzen.

### VectorStore ist ein Singleton pro Instanz
`VectorStore.for_instance(config, slug)` cached die Instanz im Modul-Level-Dict `_store_cache`. Der Index wird einmalig in `__init__` über `_ensure_index()` erstellt. Nie direkt `VectorStore(...)` aufrufen — immer `for_instance()` nutzen. `instance_service.delete_instance()` invalidiert den Cache-Eintrag.

### Ingestion-Pipeline
```
PDF → fitz (PyMuPDF) → Seiten-Text
    → ChunkSplitter.split_into_chunks()          # Token-basierter RecursiveCharacterTextSplitter
    → ChunkSplitter.add_neighbouring_content()   # Vor-/Nach-Kontext anhängen + _truncate_to_tokens(600) intern
    → DocumentProcessor._embed_chunks()           # max. 3 gleichzeitig via asyncio.Semaphore(3)
        → process_chunk()                          # _truncate_to_tokens (2. Sicherheitsstufe) + asyncio.to_thread(store.add_texts())
    → RedisMetadataService.save_document_metadata()
```

**Token-basiertes Chunking:** `CHUNK_SIZE` und `CHUNK_OVERLAP` sind in **Tokens** (nicht Zeichen). Der HuggingFace-Tokenizer wird über `_load_tokenizer()` in `chunk_splitter.py` bereitgestellt (`@lru_cache(maxsize=4)` — prozessweit gecacht pro Modell-ID). Sowohl `DocumentProcessor` als auch `ChunkSplitter` rufen `_load_tokenizer()` auf, laden den Tokenizer aber nur einmal tatsächlich. Beim ersten App-Start wird der `BAAI/bge-m3`-Tokenizer (XLM-RoBERTa SentencePiece) von HuggingFace Hub heruntergeladen (~1 MB) — im Docker-Image ist er vorgebaut.

**Duplikat-Erkennung:** SHA-256-Hash der Datei wird vor der Verarbeitung gegen Redis geprüft. Bereits indizierte Dateien werden übersprungen.

### Retrieval — Hybrid Search in `rag.retrieve()`

`vector_store.hybrid_search(query, k=HYBRID_K)` ruft OpenSearch mit einer `hybrid`-Query auf, die BM25 und kNN kombiniert:

```
query
  → OllamaEmbeddings.embed_query()          # Vektor für kNN
  → OpenSearch hybrid query:
      match(text, query)                    # BM25 — Lexik, Eigennamen, Akronyme
      knn(vector_field, vector, k)          # Semantische Ähnlichkeit
  → normalization-processor pipeline:
      min_max-Normalisierung beider Scores
      arithmetic_mean(weights=[0.4, 0.6])   # Konfigurierbar via HYBRID_BM25_WEIGHT/HYBRID_KNN_WEIGHT
  → Ergebnisse nach kombiniertem Score sortiert
  → retrieve() filtert Chunks mit Score < HYBRID_SCORE_THRESHOLD (Standard: 0.1)
```

**Pipeline-Setup:** `VectorStore.__init__()` legt die Search-Pipeline per `PUT /_search/pipeline/{name}` an (idempotent — wird bei jedem Start aktualisiert).

### SSE-Streaming
Chat-Antworten und Dokument-Uploads werden als Server-Sent Events gestreamt:

- **Chat** (`/chat/stream`): `chat_service.stream_answer()` ist ein synchroner Generator, der via `iterate_in_threadpool()` im Thread-Pool läuft. Die Route lädt die letzten 3 `ChatHistory`-Einträge aus PostgreSQL und übergibt sie als Gesprächskontext. Sendet drei Event-Typen: `event: sources` (Quell-Chunks als JSON), `data: <token>` (LLM-Token, JSON-kodiert), `event: done` (vollständige Antwort für History-Speicherung).
- **Upload** (`/documents/upload`): Async-Generator, sendet Fortschritts-JSON pro Datei.

### Asynchronität
FastAPI läuft auf uvicorn (asyncio). Alle blockierenden I/O-Operationen werden mit `asyncio.to_thread()` umhüllt — insbesondere:
- `VectorStore.for_instance()` bei Cache-Miss (OpenSearch-HTTP)
- `DocumentProcessor.__init__()` (Tokenizer-Laden)
- `store.add_texts()` in `process_chunk()`
- LDAP-Authentifizierung in `routes/auth.py`

Redis-Operationen sind nativ async (`redis.asyncio`).

### Authentifizierung
Login via LDAP (`ldap_service.authenticate()`): Bind als Benutzer, prüft `pwdAccountLockedTime` und `shadowExpire`. Optional: LDAP-Gruppen-Check für Global-Admin-Status (`LDAP_ADMIN_GROUP_DN`). Fallback: lokales Passwort-Hash (bcrypt) für Admin-Bootstrap ohne LDAP.

Sessions werden als zufällige Tokens (32 Byte urlsafe) in PostgreSQL gespeichert. `AuthMiddleware` prüft das Cookie bei jedem Request. Session-Lifetime: `SESSION_LIFETIME_HOURS` (Standard: 8h).

### Bedrock-Support (inaktiv)
`langchain_aws` wird lazy importiert (nur wenn `EMBEDDER_TYPE=bedrock` oder `LLM_TYPE=bedrock`). AWS-Variablen sind in `LoaderConfig` vorhanden. Bedrock ist nicht getestet in dieser Deployment-Umgebung.

## Häufige Aufgaben

### Datenbankmigrationen (Alembic)

```bash
# Schema der laufenden Datenbank prüfen
alembic current

# Neue Migration aus Modelländerungen ableiten
alembic revision --autogenerate -m "kurze_beschreibung"
# → generierte Datei in alembic/versions/ immer manuell prüfen!

# Migration einspielen (passiert im Container automatisch beim Start)
alembic upgrade head

# Rollback
alembic downgrade -1

# Bestehende Datenbank (vor Alembic-Einführung) als aktuell markieren
alembic stamp head
```

### Lokale Entwicklung (ohne Docker)
```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
pip install -e .                        # Installiert src/ als package
# infra/.env muss existieren
alembic upgrade head                    # Schema anlegen
uvicorn app.app_fastapi:app --reload --port 8081
```
Voraussetzung: OpenSearch, Redis und PostgreSQL laufen (z.B. via `docker compose up opensearch redis postgres -d`).

### Ersten Admin anlegen
```bash
docker exec -it app python -m app.cli.admin create-admin <username> <password>
```
Oder lokal: `python -m app.cli.admin create-admin <username> <password>`

### Bulk-Ingestion via CLI
```bash
python -m app.ingest --instance <slug> /pfad/zu/pdfs/ --recursive
python -m app.ingest --instance <slug> einzelne.pdf weitere.pdf
```
Funktioniert lokal und im Container (`docker exec -it app python -m app.ingest ...`).

### OpenSearch-Index zurücksetzen
```bash
curl -X DELETE http://localhost:9200/documents_<slug>
# Danach App neu starten; Index wird automatisch neu angelegt
```
Redis-Metadaten separat löschen:
```bash
docker exec -it $(docker ps -qf name=redis) redis-cli FLUSHDB
```

### Logs
```bash
docker compose -f infra/docker-compose.yml logs -f app
docker compose -f infra/docker-compose.yml logs -f opensearch
```

### Neues Modell verwenden
1. `LLM_MODEL=<modell>` in `infra/.env` setzen
2. `ollama pull <modell>` auf dem Host ausführen
3. App-Container neu starten: `docker compose restart app`
4. Wenn sich `EMBEDDINGS_MODEL` ändert: Index löschen und neu aufbauen (Dimension kann abweichen)

## Invarianten — nicht brechen

- **`EMBEDDING_SIZE` muss mit dem tatsächlichen Modell übereinstimmen** — falscher Wert → OpenSearch-Index mit falscher Dimension → alle Embeddings ungültig
- **`number_of_replicas: 0`** im Index-Mapping — Single-Node-OpenSearch; auf 1 setzen würde Index auf YELLOW bringen
- **`DocumentProcessor` benötigt immer `vector_store`** — wirft `ValueError` im `__init__` ohne es
- **`load_documents()` ist ein async generator** — muss mit `async for` konsumiert werden, nicht mit `await`
- **`load_dotenv(..., override=False)`** — docker-compose-Env hat Vorrang vor der .env-Datei
- **`CHUNK_SIZE`/`CHUNK_OVERLAP` sind in Tokens** — Änderung erfordert Index-Neuaufbau (Chunks wurden anders geschnitten)
- **`TOKENIZER_MODEL_ID` muss zum `EMBEDDINGS_MODEL` passen** — bge-m3 → `BAAI/bge-m3`
- **`VectorStore.for_instance()` statt `VectorStore()`** — direkte Instanziierung umgeht den Cache

## Was nicht in CLAUDE.md gehört

Deployment-Details zu HTTPS und Ressourcenlimits sind bewusst ausgelassen — diese Deployment-Umgebung ist intern/privat. Änderungen daran erfordern eine explizite Entscheidung des Teams.
