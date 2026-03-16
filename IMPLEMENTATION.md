# Synapse — Minimal Implementation (Local‑First)

This document describes the **implemented** minimal Synapse system in this repository. It is intended to be ingested by an LLM when planning future phases.

## Summary

Synapse provides:

- Persistent storage of captured “memories” (plain text)
- Embedding generation via **Ollama**
- Automatic **classification** of captures (using embedding similarity to category prototypes)
- Vector similarity search via **PostgreSQL + pgvector**
- An **MCP (Model Context Protocol)** server that exposes two tools:
  - `capture_memory`
  - `search_memories`
- Optional **Matrix**: in-stack Synapse homeserver + local TLS proxy (Element X friendly) + ingestion bot

Everything runs in containers **except Ollama**, which is assumed to already be running (local-first).

---

## Architecture

```text
AI Client
  │
  ▼
MCP Server (HTTP JSON-RPC)
  │  calls
  ▼
Memory API (FastAPI)
  │  embeds via HTTP
  ├──────────────► Ollama (/api/embeddings)
  │
  ▼
Postgres (pgvector)

Matrix User (Element X)
  │  HTTPS (LAN/VPN)
  ▼
Matrix TLS Proxy (Caddy, internal CA)
  │
  ▼
Matrix Synapse Homeserver

Matrix Bot (optional) ──calls──► Memory API
```

### Components

1. **Postgres service** (`pgvector/pgvector:pg15`)
   - Stores captures + memories
   - Stores embeddings as `VECTOR(768)`
   - Provides cosine-distance search via pgvector operators

2. **API service** (`api/`)
   - FastAPI app: `api/app/main.py`
   - Endpoints:
     - `POST /capture`
     - `GET /search`
   - Calls Ollama to generate embeddings

3. **MCP service** (`mcp/`)
   - FastAPI app: `mcp/server.py` (Streamable HTTP)
   - Stdio entrypoint: `mcp/stdio_server.py` (for desktop clients)
   - Translates MCP tool calls into API requests (thin adapter; no business logic)

---

## Repository layout

```text
.
├── docker-compose.yml
├── .env.example
├── db/
│   └── init.sql
├── api/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── __init__.py
│       ├── main.py
│       ├── config.py
│       ├── db.py
│       ├── embeddings.py
│       ├── classify.py
│       ├── models.py
│       └── search.py
├── mcp/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── server.py
│   └── stdio_server.py
├── matrix/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── bot.py
├── matrix-homeserver/
│   ├── Dockerfile
│   └── entrypoint.sh
├── matrix-proxy/
│   └── entrypoint.sh
└── docs/
    └── architecture.md
```

---

## Configuration (environment variables)

Copy `.env.example` to `.env` and adjust as needed.

### Postgres

- `POSTGRES_HOST` (default `postgres`)
- `POSTGRES_PORT` (default `5432`)
- `POSTGRES_DB` (default `synapse`)
- `POSTGRES_USER` (default `synapse`)
- `POSTGRES_PASSWORD` (default `synapse`)

### Ollama

- `OLLAMA_HOST` (default `host.docker.internal`)
- `OLLAMA_PORT` (default `11434`)
- `EMBED_MODEL` (default `nomic-embed-text`)

Remote Ollama is supported by setting `OLLAMA_HOST` to a reachable IP/hostname (for example `100.104.36.96` on your home network/VPN).

### Matrix (optional)

The compose profile `matrix` adds three services:
- `matrix-synapse`: Matrix homeserver (Synapse)
- `matrix-proxy`: Caddy reverse proxy with local TLS (internal CA) for Element X
- `matrix-bot` (optional): captures room messages into Synapse

Homeserver config:
- `MATRIX_SERVER_NAME` (default `localhost`)
- `MATRIX_HTTP_PORT` (default `8008`)
- `MATRIX_TLS_PORT` (default `8448`)
- `MATRIX_REPORT_STATS` (default `no`)

TLS proxy discovery config:
- `MATRIX_PUBLIC_BASE_URL` (optional): what `/.well-known/matrix/client` returns for `m.homeserver.base_url`.
  - Recommended: set this to the exact homeserver URL you’ll enter in Element X, e.g. `https://mac-workstation`.
- `MATRIX_PUBLIC_SERVER_NAME` (optional): what `/.well-known/matrix/server` returns for `m.server` (federation discovery).

Element X connection URL:
- Preferred: `https://<host>` (port 443)
- Alternate: `https://<host>:<MATRIX_TLS_PORT>`

Caddy internal CA root cert path (inside the proxy container):
- `/data/pki/authorities/local/root.crt`

Operational notes:
- Synapse generates `homeserver.yaml` into its persistent `/data` volume on first run. If you need to change `MATRIX_SERVER_NAME` after initial start, wipe the Matrix volume to regenerate config.
- Registration is enabled by default for local-only usage; do not expose this to the public internet.

Bot config (only required if you want ingestion):
- `MATRIX_HOMESERVER` (default `http://matrix-synapse:8008`)
- `MATRIX_USER_ID`
- `MATRIX_ACCESS_TOKEN`
- `MATRIX_ROOM_ID`

**Important:** the embedding model must exist in Ollama (e.g. `ollama pull nomic-embed-text`).

### API

- Exposed on host port `API_PORT` (default `8000`)

### MCP

- Exposed on host port `MCP_PORT` (default `8080`)
- `API_BASE_URL` (default `http://api:8000`) — internal URL used by the MCP container to reach the API.
- `MCP_ALLOWED_ORIGINS` — comma-separated list of allowed origins for requests that include an `Origin` header.
  - If an `Origin` header is present and not allowed, the MCP server returns HTTP 403.
  - If no `Origin` header is present (typical non-browser clients), requests are accepted.

---

## Database schema

Initialized by `db/init.sql`.

### Classification

Captures can store classification metadata in `captures.classification` (JSONB), along with `classification_model` and `classified_at`.
The API classifies content using embedding similarity to a small set of category prototypes (no extra LLM required beyond embeddings).

### Extensions

- `vector` (pgvector)
- `pgcrypto` (for `gen_random_uuid()`)

### Tables

`captures`

- `id` UUID PK
- `source` TEXT nullable
- `content` TEXT not null
- `created_at` TIMESTAMPTZ default `now()`

`memories`

- `id` UUID PK
- `capture_id` UUID FK → captures(id)
- `content` TEXT not null
- `embedding` VECTOR(768)

### Index

`memories_embedding_idx` is an **ivfflat** index on `embedding` using cosine distance:

```sql
CREATE INDEX memories_embedding_idx
ON memories
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
```

Notes:
- ivfflat is approximate; on very small datasets an index scan can occasionally be unhelpful.
- The API includes a defensive fallback to an exact scan if an approximate search returns no rows.
- For performance tuning as data grows, adjust `lists` and run `ANALYZE`.

---

## API service

Base URL: `http://localhost:8000`

### `POST /capture`

Stores a memory and its embedding.

Request body:

```json
{
  "content": "string",
  "source": "optional string"
}
```

Processing:
1. Generate embedding via Ollama `POST /api/embeddings`
2. Classify the capture using embedding similarity to category prototypes
3. Insert into `captures` (including classification metadata)
4. Insert into `memories` with the embedding

Response:

```json
{
  "status": "stored",
  "id": "<memory uuid>",
  "classification": {
    "category": "idea",
    "confidence": 0.83,
    "method": "embedding-prototypes"
  }
}
```

Error behavior:
- If Ollama is unreachable or returns an error: HTTP 503 with a clear message
- If embedding dimension != 768: HTTP 500 (schema mismatch)
- If DB is unavailable: HTTP 503

### `GET /search`

Semantic search over stored memories.

Query parameters:
- `query` (required)
- `limit` (default 5, range 1–50)

Processing:
1. Generate embedding for `query` via Ollama
2. Run cosine similarity search:

```sql
SELECT content, 1 - (embedding <=> :query_vec) AS score
FROM memories
WHERE embedding IS NOT NULL
ORDER BY embedding <=> :query_vec
LIMIT :limit;
```

Response:

```json
{
  "results": [
    {
      "content": "...",
      "score": 0.82,
      "classification": {
        "category": "work",
        "confidence": 0.71,
        "method": "embedding-prototypes"
      }
    }
  ]
}
```

---

## MCP service

Endpoint: `http://localhost:8080/mcp`

Transport: MCP **Streamable HTTP** (minimal implementation)

- `GET /mcp` returns **405** (SSE stream not implemented in this minimal build)
- `POST /mcp` accepts a single JSON-RPC message and returns `application/json`
- Notifications (messages without `id`) are accepted and return **202**

### Implemented MCP methods

- `initialize`
  - Negotiates protocol version. Supported: `2025-11-25`, `2025-03-26`
  - Declares `tools` capability
- `notifications/initialized`
  - Accepted (notification)
- `ping`
  - Returns `{}`
- `tools/list`
  - Returns the two Synapse tools
- `tools/call`
  - Executes `capture_memory` or `search_memories`

### Tools

#### `capture_memory`

Arguments:

```json
{ "content": "...", "source": "optional" }
```

Behavior:
- Calls API `POST /capture`
- Returns tool result with `structuredContent` containing the API response

#### `search_memories`

Arguments:

```json
{ "query": "...", "limit": 5 }
```

Behavior:
- Calls API `GET /search`
- Returns tool result with:
  - `structuredContent`: the API JSON
  - `content`: a JSON-serialized text block for compatibility

### Security note (Origin header)

For Streamable HTTP, browsers may send an `Origin` header. To mitigate DNS rebinding risk:
- If `Origin` is present, it must match `MCP_ALLOWED_ORIGINS`.
- If you intend to call Synapse MCP from a browser-based UI, set `MCP_ALLOWED_ORIGINS` accordingly.

---

## Deployment

```bash
cp .env.example .env
docker compose up -d --build
```

Verify:

```bash
curl -sS http://localhost:8000/health
curl -sS http://localhost:8080/health
```

---

## Known limitations (intentional for minimal phase)

- No authentication / multi-user support
- No SSE streaming for MCP (POST-only JSON responses)
- No background ingestion, summarization, or entity extraction
- Embedding dimension fixed to 768 (schema + code)

---

## Extension points / future phases

Common next steps that fit this design:

1. **Auth**
   - Add API key or OAuth/JWT at API and MCP layers

2. **Metadata + filtering**
   - Add tags, timestamps, or structured fields on `captures`
   - Add SQL filters + hybrid search (keyword + vector)

3. **More MCP capabilities**
   - Expose memories as MCP Resources
   - Add prompts for summarization workflows
   - Implement SSE stream support for Streamable HTTP

4. **Index tuning / scaling**
   - Increase ivfflat `lists` and set `ivfflat.probes`
   - Consider HNSW indexes for higher recall on larger datasets
