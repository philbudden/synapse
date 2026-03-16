# Synapse Architecture

Synapse is a minimal, container-native persistent memory system.

```text
AI Client → MCP Server → Memory API → (Ollama embeddings) → Postgres (pgvector)
```

## Responsibilities

| Component | Responsibility |
|---|---|
| PostgreSQL + pgvector | Persistent storage + vector similarity search |
| Memory API (FastAPI) | Capture, embedding generation via Ollama, and search logic |
| MCP server | Thin tool adapter for AI clients; no business logic |

## Services (docker compose)

- **postgres**: `pgvector/pgvector:pg15`
  - Initializes schema from `db/init.sql` (safe to re-run)
  - Stores `captures` and `memories` (with `VECTOR(768)` embeddings)

- **api**: FastAPI on port 8000
  - `POST /capture` → insert capture + embed via Ollama + store memory
  - `GET /search` → embed query + cosine similarity search

- **mcp**: MCP server on port 8080
  - Streamable HTTP: `POST /mcp`
  - Tools: `capture_memory`, `search_memories`

- **matrix-bot** (optional profile: `matrix`)
  - Listens for messages in a configured Matrix room
  - Calls `POST /capture` on the API and replies with the stored ID + category

## External dependency

- **Ollama** is an external dependency (not containerized). The API calls:
  - `POST http://{OLLAMA_HOST}:{OLLAMA_PORT}/api/embeddings`
