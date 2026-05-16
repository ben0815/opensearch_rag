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
- OpenSearch Dashboards: http://localhost:5601
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
    → ChunkSplitter.split_into_chunks()       # RecursiveCharacterTextSplitter
    → ChunkSplitter.add_neighbouring_content() # Fügt Vor-/Nach-Kontext an
    → content[:450]                            # Hard-Truncation: mxbai-embed-large hat 512 Token Limit
    → asyncio.to_thread(store.add_texts())    # Synchrones OpenSearch in Thread auslagern
    → RedisMetadataService.save_document_metadata()
```

**Duplikat-Erkennung:** SHA-256-Hash der Datei wird vor der Verarbeitung gegen Redis geprüft. Bereits indizierte Dateien werden übersprungen (`yield 100.0; return`).

### Retrieval — zwei Strategien in `rag.search()`
1. `similarity_search_with_relevance_scores(k=5, score_threshold=0.5)` → echte Scores in `doc.metadata['score']`
2. `max_marginal_relevance_search(k=3, fetch_k=10, lambda_mult=0.7)` → Score wird als `'MMR'`-String gesetzt

Ergebnisse werden dedupliziert (nach `page_content`) und nach numerischem Score sortiert (MMR-only ans Ende).

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
- **Chunk-Inhalt wird auf 450 Zeichen gekürzt** (in `process_chunk` und `add_neighbouring_content`) — nicht erhöhen ohne Modellwechsel

## Was nicht in CLAUDE.md gehört

Deployment-Details zu Authentifizierung, HTTPS und Ressourcenlimits sind bewusst ausgelassen — diese Deployment-Umgebung ist intern/privat. Änderungen daran erfordern eine explizite Entscheidung des Teams.
