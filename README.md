# OpenSearch RAG

Multi-mandantenfähige RAG-Anwendung (Retrieval-Augmented Generation) auf Basis von FastAPI, OpenSearch und Ollama. PDFs werden in token-basierte Chunks zerlegt, mit lokalen Embedding-Modellen vektorisiert und in mandantenspezifischen OpenSearch-Indizes gespeichert. Benutzer authentifizieren sich via LDAP und können Dokumente hochladen sowie im Chat befragen.

## Funktionsumfang

- **Multi-Tenant**: Instanzen (Dokumentsammlungen) mit Rollen `viewer` (Chat) und `manager` (Upload/Löschen)
- **Hybrid Search**: BM25 + kNN mit konfigurierbaren Gewichten, Score-Normalisierung via OpenSearch Pipeline
- **SSE-Streaming**: LLM-Antworten und Upload-Fortschritt werden live gestreamt
- **LDAP-Auth**: Bind als Benutzer, Account-Status-Prüfung (`pwdAccountLockedTime`, `shadowExpire`), optionaler Admin-Gruppen-Check; lokaler bcrypt-Fallback für Bootstrap-Admin
- **Admin-UI**: Instanzen, Gruppen und Benutzer verwalten; globale LLM/Such-Parameter live anpassbar; System-Status-Dashboard; per-Instanz BM25-Sprachanalyzer und LLM-Parameter konfigurierbar
- **Chat-Verlauf**: durchsuchbar, nach Instanz filterbar; letzten 3 Frage/Antwort-Paare fließen als Gesprächskontext in Folgefragen ein
- **Rate Limiting**: Login auf 10 Versuche/Minute, Chat-Stream auf 30 Anfragen/Minute begrenzt

## Voraussetzungen

- Docker und Docker Compose
- Ollama läuft **lokal auf dem Host** (`ollama serve`), nicht im Container

```bash
ollama pull bge-m3              # Embedding-Modell (multilingual, 1024 dim)
ollama pull qwen3.5:35b         # LLM — 35B Parameter, nur 3B aktiv (MoE), empfohlen
# Alternativ für mehr Kapazität:
# ollama pull qwen3.5:122b      # 122B Parameter, nur 10B aktiv
```

## Schnellstart

```bash
# 1. Konfiguration anlegen
cp infra/.env.example infra/.env
# infra/.env nach Bedarf anpassen (Passwörter, Modellnamen, LDAP-URL …)

# 2. Stack starten
cd infra && docker compose up -d

# 3. Ersten Admin anlegen
docker exec -it app python -m app.cli.admin create-admin <benutzername> <passwort>
```

Die Web-App ist danach unter **http://localhost:8081** erreichbar.

## Konfiguration

Alle Variablen werden in `infra/.env` gesetzt (Vorlage: `infra/.env.example`). Im Docker-Betrieb werden sie von docker-compose geladen; bei lokaler Entwicklung ohne Docker liest die App die `.env`-Datei direkt über `load_dotenv`.

### Überblick aller Variablen

| Variable | Standard | Beschreibung |
|---|---|---|
| `OLLAMA_HOST` | `http://host.docker.internal:11434` | Ollama-URL (Host-intern) |
| `EMBEDDINGS_MODEL` | `bge-m3` | Embedding-Modell (multilingual, 1024 dim) |
| `EMBEDDING_SIZE` | `1024` | Vektor-Dimension — muss exakt zum Modell passen |
| `LLM_MODEL` | `qwen3.5:35b` | Sprachmodell für Chat-Antworten |
| `LLM_TEMPERATURE` | `0.0` | Kreativität des LLM (0.0 = deterministisch) |
| `LLM_TIMEOUT_SECONDS` | `240` | Maximale Wartezeit auf LLM-Antwort |
| `LLM_NUM_CTX` | `16384` | Kontextfenster des LLM in Tokens |
| `CHUNK_SIZE` | `400` | Chunk-Größe in Tokens |
| `CHUNK_OVERLAP` | `60` | Überlapp zwischen Chunks in Tokens |
| `EMBEDDING_MAX_TOKENS` | `600` | Token-Limit pro Chunk vor dem Embedding |
| `TOKENIZER_MODEL_ID` | `BAAI/bge-m3` | HuggingFace-Tokenizer für Token-Zählung |
| `OPENSEARCH_ANALYZER` | `standard` | Globaler Fallback-Analysator für BM25 — wird pro Instanz beim Anlegen überschrieben |
| `HYBRID_BM25_WEIGHT` | `0.4` | Gewichtung der Volltextsuche (BM25) im Hybrid-Score |
| `HYBRID_KNN_WEIGHT` | `0.6` | Gewichtung der Vektorsuche (kNN) im Hybrid-Score |
| `HYBRID_K` | `10` | Anzahl zurückgegebener Kandidaten pro Suche |
| `HYBRID_SCORE_THRESHOLD` | `0.1` | Mindest-Score; Treffer darunter werden verworfen |
| `SESSION_LIFETIME_HOURS` | `8` | Gültigkeit einer Login-Session in Stunden |
| `LDAP_URL` | `ldap://ldap:389` | LDAP-Server-URL |
| `LDAP_BASE_DN` | `dc=example,dc=com` | Basis-DN des LDAP-Verzeichnisses |
| `LDAP_USER_SEARCH_BASE` | `ou=users,dc=example,dc=com` | Suchbasis für Benutzerkonten |
| `LDAP_BIND_DN` | _(leer)_ | Service-Account für LDAP-Suche (optional) |
| `LDAP_BIND_PASSWORD` | _(leer)_ | Passwort des Service-Accounts (optional) |
| `LDAP_USER_FILTER` | `(objectClass=inetOrgPerson)` | LDAP-Filter für gültige Benutzerkonten |
| `LDAP_UID_ATTR` | `uid` | LDAP-Attribut für den Benutzernamen |
| `LDAP_DISPLAY_NAME_ATTR` | `displayName` | LDAP-Attribut für den Anzeigenamen |
| `LDAP_MAIL_ATTR` | `mail` | LDAP-Attribut für die E-Mail-Adresse |
| `LDAP_ADMIN_GROUP_DN` | _(leer)_ | DN der Admin-Gruppe (optional) |
| `POSTGRES_PASSWORD` | `changeme` | Passwort für die PostgreSQL-Datenbank |
| `REDIS_PASSWORD` | _(leer)_ | Redis-Passwort (leer = kein Passwort; in Produktion setzen) |
| `SECURE_COOKIES` | `false` | Cookies auf HTTPS-only setzen (nur mit TLS-Termination) |
| `APP_BIND_HOST` | `0.0.0.0` | Bind-Adresse des App-Ports auf dem Host. `0.0.0.0` = von allen Rechnern im Netz erreichbar (Entwicklung). In Produktion mit Caddy auf `127.0.0.1` setzen. |

---

### Modelle

#### Embedding-Modell (`EMBEDDINGS_MODEL`, `EMBEDDING_SIZE`, `TOKENIZER_MODEL_ID`)

Das Embedding-Modell wandelt Text in numerische Vektoren um. Diese Vektoren repräsentieren die *Bedeutung* des Textes und ermöglichen die semantische Suche.

**`bge-m3`** (Standard) ist ein multilinguales Modell von BAAI, das besonders gut für deutschsprachige Dokumente geeignet ist. Es versteht Semantik über Sprachgrenzen hinweg und erzeugt 1024-dimensionale Vektoren.

- `EMBEDDING_SIZE=1024` muss zur tatsächlichen Ausgabedimension des Modells passen. Bei `bge-m3` ist das immer 1024. **Kritisch**: Ein falscher Wert erzeugt einen OpenSearch-Index mit der falschen Dimension — alle gespeicherten Vektoren sind dann unbrauchbar. Bei einem Modellwechsel muss der Index gelöscht und neu aufgebaut werden.
- `TOKENIZER_MODEL_ID=BAAI/bge-m3` ist der zugehörige HuggingFace-Tokenizer, der beim ersten Start (~1 MB) heruntergeladen und dann lokal gecacht wird. Er wird für die token-basierte Chunk-Einteilung benötigt und muss immer zum Embedding-Modell passen.

#### Sprachmodell (`LLM_MODEL`)

Das Sprachmodell (LLM) formuliert die eigentliche Chat-Antwort auf Basis der gefundenen Dokumentenabschnitte.

**`qwen3.5:35b`** (Standard) verwendet eine Mixture-of-Experts-Architektur: Obwohl das Modell 35 Milliarden Parameter hat, sind bei jedem Verarbeitungsschritt nur etwa 3 Milliarden aktiv. Das macht es deutlich schneller und speichersparender als ein klassisches 35B-Modell, bei vergleichbarer Qualität.

Als Alternative steht `qwen3.5:122b` zur Verfügung (10B aktive Parameter) — bessere Qualität, aber deutlich höherer RAM-Bedarf (ca. 70 GB).

---

### Dokument-Verarbeitung (Chunking)

Beim Einlesen eines PDFs wird der Text in kleinere Abschnitte (*Chunks*) aufgeteilt, da ein LLM nicht das gesamte Dokument auf einmal verarbeiten kann.

```
PDF-Seite (z.B. 2000 Token)
    │
    ▼  split_into_chunks()
┌───────────────────┐  ┌───────────────────┐  ┌───────────────────┐
│  Chunk 1 (400 T)  │  │  Chunk 2 (400 T)  │  │  Chunk 3 (400 T)  │
└───────────────────┘  └───────────────────┘  └───────────────────┘
        ↑ 60T Overlap ↓         ↑ 60T Overlap ↓
    │
    ▼  add_neighbouring_content() + Embedding
┌──────────────────────────────────────────────────────────────────┐
│ [Prev Context ~100T] [Current Content 400T] [Next Context ~100T] │  → max. 600T → Embedding-Vektor
└──────────────────────────────────────────────────────────────────┘
```

#### `CHUNK_SIZE` (Standard: 400 Tokens)

Bestimmt die Größe jedes Abschnitts in **Tokens** (keine Zeichen). Tokens entsprechen ungefähr ¾ eines deutschen Wortes — 400 Token entsprechen ca. 250–300 Wörtern oder etwa ½ Seite Text.

- **Kleiner (z.B. 200–300)**: Jeder Chunk enthält weniger Text → präzisere Treffergenauigkeit bei Detailfragen, aber fehlender Zusammenhang für komplexere Fragen.
- **Größer (z.B. 600–800)**: Mehr Kontext pro Chunk → besser für Zusammenfassungen, aber die Vektoren werden unschärfer (ein Vektor repräsentiert mehr unterschiedliche Themen).
- **Achtung**: Eine Änderung erfordert den vollständigen Neu-Aufbau aller Indizes, da die alten Chunks anders geschnitten sind.

#### `CHUNK_OVERLAP` (Standard: 60 Tokens)

Bestimmt, wie viele Tokens am Ende eines Chunks auch am Anfang des nächsten Chunks wiederholt werden. Verhindert, dass ein Satz, der genau an einer Chunk-Grenze liegt, in der Suche nicht gefunden wird.

- **Zu klein (< 20)**: Sätze an Grenzen fallen durch das Raster.
- **Zu groß (> 100)**: Chunks enthalten viel redundanten Inhalt → mehr gespeicherte Daten, langsamere Suche.

#### `EMBEDDING_MAX_TOKENS` (Standard: 600 Tokens)

Jeder gespeicherte Chunk besteht aus dem eigentlichen Inhalt (bis zu 400 Tokens) plus Kontext aus den Nachbar-Chunks (je ~100 Tokens). `EMBEDDING_MAX_TOKENS=600` setzt die harte Obergrenze: Falls der kombinierte Text länger ist, wird er auf 600 Tokens abgeschnitten, bevor der Embedding-Vektor berechnet wird.

`bge-m3` unterstützt bis zu 8192 Tokens, also gibt es hier keinen technischen Engpass — der Wert kann bei Bedarf erhöht werden, wenn der Kontext vergrößert wird.

#### `OPENSEARCH_ANALYZER` (Standard: `standard`)

Steuert die Textverarbeitung für die BM25-Volltextsuche. Typische Werte:

- **`standard`**: Keine Sprachspezifika — geeignet für mehrsprachige oder gemischte Inhalte. **Empfohlener Standard.**
- **`german`**: Entfernt deutsche Stoppwörter (*der, die, das, und, …*), führt Snowball-Stemming durch (*"Dokumente" → "Dokument"*) und normalisiert Umlaute (*"ü" → "u"*).
- **`english`**, **`french`**, **`spanish`**, **`italian`**, **`portuguese`**, **`dutch`**, **`russian`**, **`arabic`** u.v.m. — OpenSearch unterstützt über 30 Sprach-Analyzer.

**Pro Instanz konfigurierbar**: Der Analyzer wird beim Anlegen einer Instanz in der Admin-UI ausgewählt und im Index-Mapping der Instanz fest verankert. Nach dem Anlegen kann er nicht mehr geändert werden. `OPENSEARCH_ANALYZER` in der `.env` gilt nur als Fallback, wenn keine Instanz-spezifische Einstellung vorliegt.

**Achtung bei manuellen Änderungen**: Eine nachträgliche Änderung des Analyzers erfordert den vollständigen Neu-Aufbau des Indexes, da der Analyzer beim Indexieren und beim Suchen übereinstimmen muss.

---

### Hybrid Search (Retrieval)

Wenn ein Benutzer eine Frage stellt, wird nach passenden Dokument-Chunks gesucht, bevor das LLM antwortet. Die Suche kombiniert zwei komplementäre Verfahren:

- **BM25** (Volltextsuche): Findet Chunks, die exakt dieselben Wörter wie die Frage enthalten. Besonders gut bei Eigennamen, Akronymen und technischen Begriffen.
- **kNN** (Vektorsuche): Findet Chunks mit ähnlicher *Bedeutung*, auch wenn andere Wörter verwendet werden. Gut bei Synonymen und umgangssprachlichen Formulierungen.

OpenSearch normalisiert beide Scores auf [0, 1] und berechnet dann einen gewichteten Mittelwert.

#### `HYBRID_BM25_WEIGHT` / `HYBRID_KNN_WEIGHT` (Standard: 0.4 / 0.6)

Die Gewichte müssen sich zu 1.0 addieren. Empfehlungen:

| Dokumententyp | BM25 | kNN | Begründung |
|---|---|---|---|
| Technische Handbücher, Gesetze (viele Fachbegriffe) | 0.5 | 0.5 | Exakte Begriffe sind kritisch |
| Allgemeine Unternehmenstexte (Standard) | 0.4 | 0.6 | Gute Balance |
| Freitext, Berichte (variierender Wortschatz) | 0.3 | 0.7 | Semantik schlägt Lexik |

#### `HYBRID_K` (Standard: 10)

Wie viele Kandidaten OpenSearch pro Suche zurückgibt (vor Deduplizierung und Score-Filterung). Eine höhere Zahl erhöht die Chance, relevante Chunks zu finden, vergrößert aber auch den Kontext, der an das LLM übergeben wird, und damit den RAM- und Zeitbedarf.

#### `HYBRID_SCORE_THRESHOLD` (Standard: 0.1)

Chunks mit einem kombinierten Score unter diesem Schwellwert werden **vor der LLM-Anfrage** verworfen. Verhindert, dass thematisch unpassende Abschnitte die Antwort verfälschen.

- **`0.0`**: Deaktiviert — alle K Ergebnisse werden verwendet, auch schwache.
- **`0.05–0.1`**: Konservativ — filtert nur offensichtlich irrelevante Treffer.
- **`0.15–0.2`**: Strenger — für homogene Dokumentensammlungen, wo schwache Treffer mit hoher Wahrscheinlichkeit thematisch falsch sind.

Wenn das LLM häufig "Die gesuchte Information wurde nicht gefunden." antwortet, obwohl passende Dokumente vorhanden sind, den Schwellwert senken. Wenn irrelevante Informationen in die Antwort einfließen, den Schwellwert erhöhen.

---

### LLM-Parameter

#### `LLM_TEMPERATURE` (Standard: 0.0)

Steuert, wie kreativ oder deterministisch das LLM antwortet:

- **`0.0`**: Vollständig deterministisch — bei gleicher Frage immer die gleiche Antwort. Ideal für faktische Dokumentensuche, wo Präzision wichtiger ist als Variabilität.
- **`0.1–0.5`**: Leichte Variabilität — die Antwort kann unterschiedlich formuliert sein, bleibt aber inhaltlich konsistent.
- **`> 0.7`**: Kreativ, aber unzuverlässig für Fakten — nicht empfohlen für diesen Anwendungsfall.

#### `LLM_TIMEOUT_SECONDS` (Standard: 240)

Wie lange die App auf eine vollständige LLM-Antwort wartet, bevor die Verbindung abbricht. Große Modelle oder lange Antworten brauchen mehr Zeit.

**Kopplung mit dem Frontend**: Der Browser-seitige Timeout wird automatisch aus `LLM_TIMEOUT_SECONDS + 30 s` berechnet und beim Laden der Chat-Seite als `window._LLM_STREAM_TIMEOUT_MS` injiziert. Eine manuelle Anpassung in `chat.js` ist nicht mehr nötig.

#### `LLM_NUM_CTX` (Standard: 16384)

Die Größe des Kontextfensters in Tokens, das Ollama für das LLM reserviert. Das Kontextfenster enthält den gesamten Prompt: Systemanweisung + Gesprächsverlauf + Dokumenten-Chunks + Frage.

Grobe Schätzung für die Standardkonfiguration:
- 10 Chunks × 600 Token = 6.000 Token
- Systemprompt + Frage = ~500 Token
- Gesprächsverlauf (3 Einträge) = ~1.000 Token
- **Gesamt ≈ 7.500 Token** → 16.384 bietet ausreichend Puffer

Ein zu kleines Kontextfenster führt dazu, dass Ollama Chunks stillschweigend abschneidet, was die Antwortqualität verschlechtert. Ein zu großes Fenster belegt mehr GPU-VRAM.

---

### LDAP-Konfiguration

Die App authentifiziert Benutzer über LDAP (z.B. Active Directory oder OpenLDAP). Beim Login wird ein LDAP-Bind als der Benutzer selbst durchgeführt — das Passwort verlässt niemals die App.

| Variable | Bedeutung |
|---|---|
| `LDAP_URL` | URL des LDAP-Servers, z.B. `ldap://192.168.1.10:389` oder `ldaps://...` für TLS |
| `LDAP_BASE_DN` | Wurzel des Verzeichnisbaums, z.B. `dc=firma,dc=de` |
| `LDAP_USER_SEARCH_BASE` | Wo nach Benutzerkonten gesucht wird, z.B. `ou=Mitarbeiter,dc=firma,dc=de` |
| `LDAP_BIND_DN` | Optional: Ein Service-Account-DN, wenn anonymes Suchen nicht erlaubt ist |
| `LDAP_BIND_PASSWORD` | Passwort des Service-Accounts |
| `LDAP_USER_FILTER` | LDAP-Filter, der gültige Benutzerkonten identifiziert. Standard: `(objectClass=inetOrgPerson)`. Für Active Directory: `(objectClass=user)` |
| `LDAP_UID_ATTR` | LDAP-Attribut, das den Benutzernamen enthält. Standard: `uid`. AD: `sAMAccountName` |
| `LDAP_DISPLAY_NAME_ATTR` | Attribut für den Anzeigenamen. Standard: `displayName` |
| `LDAP_MAIL_ATTR` | Attribut für die E-Mail-Adresse. Standard: `mail` |
| `LDAP_ADMIN_GROUP_DN` | Optional: DN einer LDAP-Gruppe, deren Mitglieder automatisch globale Admins werden, z.B. `cn=rag-admins,ou=groups,dc=firma,dc=de` |

Die App prüft beim Login zusätzlich:
- `pwdAccountLockedTime`: Ist das Konto gesperrt?
- `shadowExpire`: Ist das Konto abgelaufen?

Ist kein LDAP-Server konfiguriert oder erreichbar, kann ein lokaler Bootstrap-Admin über die CLI angelegt werden (bcrypt-Hash in PostgreSQL).

> **Kritisch**: `EMBEDDING_SIZE` muss exakt zur Dimension des gewählten `EMBEDDINGS_MODEL` passen. Bei Änderung müssen alle OpenSearch-Indizes gelöscht und neu aufgebaut werden.

## Services

| Service | Port | Beschreibung |
|---|---|---|
| App (FastAPI) | 8081 | Web-UI + REST-API |
| OpenSearch | 9200 | Vektor-Datenbank |
| PostgreSQL | _(intern)_ | Benutzer, Instanzen, Sessions, Chat-History |
| Redis | 6379 | Dokument-Metadaten (Key: `doc:{slug}:{sha256}`) |
| Ollama | 11434 | Auf dem Host, nicht im Container |
| Caddy | 80 / 443 | Reverse-Proxy mit automatischem TLS (nur Produktion, Profile `caddy`) |

## Produktion mit HTTPS (Caddy)

In der Entwicklung ist die App direkt unter Port 8081 erreichbar. Für den Produktionseinsatz mit HTTPS steht ein Caddy-Reverse-Proxy vorbereitet, der über ein Docker-Compose-Profile aktiviert wird.

```bash
# infra/.env anpassen:
#   APP_BIND_HOST=127.0.0.1   # App nicht mehr direkt von außen erreichbar
#   SECURE_COOKIES=true        # Session-Cookies auf HTTPS-only setzen
#   DOMAIN=rag.example.com     # Wird im Caddyfile als {$DOMAIN} referenziert

# Stack mit Caddy starten:
docker compose --profile caddy up -d
```

Caddy bezieht automatisch ein TLS-Zertifikat via Let's Encrypt (Port 80 für ACME-Challenge, 443 für HTTPS). Die App ist intern über das Docker-Netzwerk erreichbar (`app:8081`) und wird nicht mehr direkt exponiert.

Das Caddyfile liegt unter `infra/caddy/Caddyfile` und kann für erweiterte Konfigurationen (eigene Zertifikate, Header, Rate-Limiting) angepasst werden.

## Datenbankmigrationen (Alembic)

Das Schema wird automatisch beim App-Start über `alembic upgrade head` auf den neusten Stand gebracht. Manuelle Eingriffe sind nur in Ausnahmefällen nötig.

### Neue Migration erstellen (bei Modelländerungen)

```bash
# Schema aus den SQLAlchemy-Modellen ableiten (Diff gegen aktuelle DB)
alembic revision --autogenerate -m "beschreibung_der_aenderung"

# Generierte Datei in alembic/versions/ prüfen und ggf. anpassen
# Dann einspielen:
alembic upgrade head
```

### Nützliche Alembic-Befehle

```bash
# Aktueller Migrations-Stand der Datenbank
alembic current

# History aller Migrations
alembic history --verbose

# Datenbank als "aktuell" markieren ohne DDL auszuführen
# (für bestehende Datenbanken vor Einführung von Alembic)
alembic stamp head

# SQL-Vorschau ohne Ausführung
alembic upgrade --sql head

# Rollback einer Migration
alembic downgrade -1
```

---

## Häufige Aufgaben

### Ersten Admin anlegen

```bash
docker exec -it app python -m app.cli.admin create-admin <username> <passwort>
```

### Bulk-Ingestion via CLI

```bash
# Einzelne Datei
python -m app.ingest --instance <slug> dokument.pdf

# Verzeichnis (rekursiv)
python -m app.ingest --instance <slug> /pfad/zu/pdfs/ --recursive
```

### OpenSearch-Index zurücksetzen

```bash
# Index löschen (erforderlich nach Wechsel des Embedding-Modells oder bei geänderter Chunk-Größe)
curl -X DELETE http://localhost:9200/documents_<slug>
# App neu starten — Index wird automatisch neu angelegt
docker compose -f infra/docker-compose.yml restart app
# Danach Dokumente neu einlesen:
python -m app.ingest --instance <slug> /pfad/zu/pdfs/ --recursive
```

Redis-Metadaten (Duplikat-Erkennung) separat zurücksetzen:
```bash
docker exec -it $(docker ps -qf name=redis) redis-cli FLUSHDB
```

### Logs

```bash
docker compose -f infra/docker-compose.yml logs -f app
docker compose -f infra/docker-compose.yml logs -f opensearch
```

## Lokale Entwicklung (ohne Docker)

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
pip install -e .
# infra/.env muss existieren
uvicorn app.app_fastapi:app --reload --port 8081
```

Voraussetzung: OpenSearch, Redis und PostgreSQL laufen (z. B. per `docker compose up opensearch redis postgres -d`).

## Architektur

```
Browser
  │
  ▼
FastAPI (app_fastapi.py)
  ├── AuthMiddleware      — Session-Token aus Cookie; Redirect → /login
  ├── /login /logout      — LDAP-Bind oder lokaler bcrypt-Check
  ├── /chat /chat/stream  — SSE-Streaming: sources → tokens → done
  ├── /documents /upload  — SSE-Fortschritt, chunked Datei-Lesen
  └── /admin              — Instanzen, Gruppen, Benutzer (paginiert)
         │
         ├── PostgreSQL   — User, Instance, Group, Session, ChatHistory
         ├── Redis         — DocumentMetadata als JSON (doc:{slug}:{sha256})
         └── OpenSearch    — documents_{slug}: knn_vector + text (BM25)
                                └── Hybrid Pipeline: min_max + arithmetic_mean
```
