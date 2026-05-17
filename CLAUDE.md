# CLAUDE.md — Projektkontext für Claude Code

## Was das Projekt macht

RAG-Anwendung (Retrieval-Augmented Generation): PDFs werden in Chunks zerlegt, mit einem lokalen Ollama-Modell eingebettet und in OpenSearch gespeichert. Über eine Gradio-Web-UI oder ein CLI-Tool können Dokumente hochgeladen und anschließend mit einem LLM befragt werden. Redis speichert Datei-Metadaten (kein Vektorspeicher).

## Laufzeitumgebung

Alle Dienste laufen in Docker Compose. Der Stack wird aus `infra/` gestartet:

```bash
cd infra
docker compose up -d
```

- App-UI: http://localhost:8081
- OpenSearch: http://localhost:9200
- Ollama läuft **lokal auf dem Host** (nicht im Container), erreichbar über `host.docker.internal:11434`

## Konfigurationsfluss — Single Source of Truth

```
infra/.env  ──►  docker-compose ${VAR:-default}  ──►  Container-Env  ──►  os.getenv() in LoaderConfig
                                                              ▲
                                               infra/secrets/.env  (Overrides: Passwörter, API-Keys)
                                               wird von entrypoint.sh gesourct, nach docker-compose env
```

**Regeln:**
- Alle Variablen **einmal** in `infra/.env` setzen — niemals direkt im Code hartkodieren
- `infra/secrets/.env` bleibt leer, außer für sensitive Overrides; wird mit `override=True` über die docker-compose-Env gelegt
- `infra/.env.example` ist die vollständige Referenz aller Variablen mit Beschreibung
- `infra/.env` und `infra/secrets/*.env` sind in `.gitignore` — **niemals committen**
- `load_dotenv(_env_file, override=False)` in `app_rag.py` und `ingest.py` lädt bei lokaler Entwicklung `infra/.env`; im Container ist `ENV_FILE=/app/secrets/.env`

## Kritische Constraint: Embedding-Dimension

`mxbai-embed-large` erzeugt **1024-dimensionale** Vektoren. Diese Zahl muss an drei Stellen konsistent sein:
1. `EMBEDDING_SIZE=1024` in `infra/.env`
2. `int(os.getenv('EMBEDDING_SIZE', '1024'))` in `config.py` (Default bereits korrekt)
3. OpenSearch-Index-Mapping in `vector_store.py` → `embedding_dimension = self.config.embedding_size`

Wenn ein Index mit falscher Dimension erstellt wurde, muss er manuell gelöscht werden:
```bash
curl -X DELETE http://localhost:9200/documents
```

## Projektstruktur

```
opensearch_rag/
├── Dockerfile                        # Multi-stage build; ENTRYPOINT entrypoint.sh; CMD app.app_rag
├── requirements.txt                  # Pinned third-party deps
├── setup.py                          # Package-Installation (src/ als package root)
├── infra/
│   ├── docker-compose.yml            # Alle 4 Services: opensearch, dashboards, app, redis
│   ├── .env                          # Lokale Konfiguration (nicht in Git)
│   ├── .env.example                  # Vorlage mit allen Variablen und Kommentaren
│   ├── secrets/.env                  # Sensitive Overrides (nicht in Git, darf leer bleiben)
│   ├── redis/redis.conf              # Redis-Persistenz- und Memory-Konfiguration
│   └── scripts/entrypoint.sh        # Sourcet secrets/.env, startet dann python -m "$@"
└── src/app/
    ├── app_rag.py                    # Einstiegspunkt: LoaderConfig → VectorStore → Gradio
    ├── ingest.py                     # CLI-Tool: python -m app.ingest <pdfs> [-r]
    ├── rag.py                        # search(): zwei Retrieval-Strategien + LLM-Chain
    ├── query_processor.py            # Bindeglied UI ↔ rag.search(); formatiert Ausgabe
    ├── loader/
    │   ├── config.py                 # LoaderConfig: liest alle Env-Vars via os.getenv()
    │   ├── vector_store.py           # VectorStore: OpenSearch-Index + Singleton get_store()
    │   ├── document_processor.py     # DocumentProcessor: PDF → Chunks → OpenSearch + Redis
    │   ├── chunk_splitter.py         # ChunkSplitter: RecursiveCharacterTextSplitter + Nachbarkontext
    │   ├── document_loader.py        # DocumentLoader (LangChain PyPDFLoader) — Legacy, ungenutzt
    │   └── exceptions.py            # LoaderError
    ├── metadata/
    │   └── redis_service.py          # RedisMetadataService: speichert DocumentMetadata als JSON
    ├── ui/
    │   ├── main.py                   # create_interface(): baut Gradio-Blocks zusammen
    │   ├── actions.py                # handle_file_upload, update_documents_list, show_document_details
    │   └── components/               # chat_interface, upload_accordion, documents_accordion
    └── utils/
        └── logging_config.py         # setup_logger(): strukturiertes Logging
```

## Architektur-Entscheidungen

### VectorStore ist ein Singleton
`VectorStore.get_store()` cached die `OpenSearchVectorSearch`-Instanz in `self._store`. Der Index wird einmalig in `__init__` über `_ensure_index()` erstellt (falls nicht vorhanden). Keinen neuen `VectorStore` pro Request erstellen.

### Ingestion-Pipeline
```
PDF → fitz (PyMuPDF) → Seiten-Text
    → DocumentProcessor._chunk_splitter.split_into_chunks()       # Token-basierter RecursiveCharacterTextSplitter
    → DocumentProcessor._chunk_splitter.add_neighbouring_content() # Vor-/Nach-Kontext anhängen
    → _truncate_to_tokens(content, 480)                            # Harte Token-Grenze via HF Tokenizer
    → DocumentProcessor._embed_chunks()                            # Batched asyncio.to_thread(store.add_texts())
    → RedisMetadataService.save_document_metadata()
```

**Token-basiertes Chunking:** `CHUNK_SIZE` und `CHUNK_OVERLAP` sind in **Tokens** (nicht Zeichen). Der HuggingFace-Tokenizer (`TOKENIZER_MODEL_ID`) wird einmalig in `DocumentProcessor.__init__` geladen (`@lru_cache` Singleton). Beim ersten App-Start wird er von HuggingFace Hub heruntergeladen (~1 MB) und danach gecacht.

**`ChunkSplitter` ist ein Singleton pro `DocumentProcessor`** — wird einmalig in `__init__` erzeugt, nicht pro Seite.

**Duplikat-Erkennung:** SHA-256-Hash der Datei wird vor der Verarbeitung gegen Redis geprüft. Bereits indizierte Dateien werden übersprungen (`yield 100.0; return`).

### Retrieval — Hybrid Search in `rag.search()`

`vector_store.hybrid_search(query, k=HYBRID_K)` ruft OpenSearch mit einer `hybrid`-Query auf, die BM25 und kNN kombiniert:

```
query
  → OllamaEmbeddings.embed_query()          # Vektor für kNN
  → OpenSearch hybrid query:
      match(text, query)                    # BM25 — Lexik, Eigennamen, Akronyme
      knn(vector_field, vector, k)          # Semantische Ähnlichkeit
  → normalization-processor pipeline:
      min_max-Normalisierung beider Scores
      arithmetic_mean(weights=[0.3, 0.7])   # Konfigurierbar via HYBRID_BM25_WEIGHT/HYBRID_KNN_WEIGHT
  → Ergebnisse nach combiniertem Score sortiert
```

**Pipeline-Setup:** `VectorStore.__init__()` legt die Search-Pipeline per `PUT /_search/pipeline/{name}` an (idempotent — wird bei jedem Start aktualisiert). Pipeline-Name und Gewichte sind via ENV konfigurierbar.

Ergebnisse werden nach `page_content` dedupliziert; die Pipeline-Sortierung wird beibehalten (kein eigenes Re-Ranking mehr nötig).

### Asynchronität
Die App läuft in Gradios Event-Loop. Alle blockierenden I/O-Operationen müssen mit `asyncio.to_thread()` umhüllt werden — insbesondere `store.add_texts()` und SHA-256-Hashing großer Dateien. Redis-Operationen sind nativ async (`redis.asyncio`).

### Bedrock-Support (inaktiv)
`langchain_aws` wird lazy importiert (nur wenn `EMBEDDER_TYPE=bedrock` oder `LLM_TYPE=bedrock`). AWS-Variablen (`AWS_REGION`, `BEDROCK_MODEL_ID`, etc.) sind in `LoaderConfig` vorhanden aber nicht in docker-compose. Bedrock ist nicht getestet in dieser Deployment-Umgebung.

## Häufige Aufgaben

### Lokale Entwicklung (ohne Docker)
```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
pip install -e .                        # Installiert src/ als package
# infra/.env muss existieren
python -m app.app_rag                   # Startet Gradio auf 127.0.0.1:8081
```
Voraussetzung: OpenSearch und Redis laufen (z.B. via `docker compose up opensearch redis -d`).

### Bulk-Ingestion via CLI
```bash
python -m app.ingest /pfad/zu/pdfs/ --recursive
python -m app.ingest einzelne.pdf weitere.pdf
```
Funktioniert lokal und im Container (`docker exec -it app python -m app.ingest ...`).

### OpenSearch-Index zurücksetzen
```bash
curl -X DELETE http://localhost:9200/documents
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
- **`TOKENIZER_MODEL_ID` muss zum `EMBEDDINGS_MODEL` passen** — mxbai-embed-large → `mixedbread-ai/mxbai-embed-large-v1`

## Was nicht in CLAUDE.md gehört

Deployment-Details zu Authentifizierung, HTTPS und Ressourcenlimits sind bewusst ausgelassen — diese Deployment-Umgebung ist intern/privat. Änderungen daran erfordern eine explizite Entscheidung des Teams.
