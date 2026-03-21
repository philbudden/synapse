# Synapse Architecture

Synapse is a minimal, container-native persistent memory system.

```text
AI Client → MCP Server → Memory API → (Ollama embeddings) → Postgres (pgvector + structured)
```

## Responsibilities

| Component | Responsibility |
|---|---|
| PostgreSQL + pgvector | Persistent storage + vector similarity search + structured memory |
| Memory API (FastAPI) | Capture, embedding generation via Ollama, and search logic |
| MCP server | Thin tool adapter for AI clients; builds prompt context blocks |

## Services (docker compose)

- **postgres**: `pgvector/pgvector:pg15`
  - Initializes schema from `db/init.sql` (safe to re-run)
  - Stores `captures`, `memories` (with `VECTOR(768)` embeddings), and `structured_memory`

- **api**: FastAPI on port 8000
  - `POST /capture` → insert capture + embed via Ollama + store memory
  - `GET /search` → embed query + cosine similarity search
  - `GET /structured_memory/{key}` → retrieve authoritative JSON by key

- **mcp**: MCP server on port 8080
  - MCP Streamable HTTP transport:
    - `GET /mcp` opens an SSE stream and returns `MCP-Session-Id`
    - `POST /mcp` accepts JSON-RPC 2.0 messages (inline response, or **202** + SSE delivery when `MCP-Session-Id` is provided)
    - `DELETE /mcp` closes the session
  - Tools: `capture_memory`, `search_memories`, `get_structured_memory`, `get_context` (discover via JSON-RPC `tools/list`)
  - Stdio transport is also available via `mcp/stdio_server.py` (for desktop clients)

- **matrix-synapse** (optional profile: `matrix`)
  - Matrix homeserver (Synapse) so mobile clients (Element X) can connect on LAN/VPN

- **matrix-proxy** (optional profile: `matrix`)
  - Caddy reverse proxy that provides local TLS (internal CA) for the Matrix client-server API

- **matrix-bot** (optional profile: `matrix`)
  - Listens for messages in a configured Matrix room
  - Calls `POST /capture` on the API and replies with the stored ID + category

## External dependency

- **Ollama** is an external dependency (not containerized). The API calls:
  - `POST http://{OLLAMA_HOST}:{OLLAMA_PORT}/api/embeddings`
