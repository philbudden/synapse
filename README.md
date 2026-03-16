# Synapse

Persistent AI memory: capture thoughts, generate embeddings with Ollama, store in Postgres (pgvector), and retrieve via semantic search. Includes an MCP (Model Context Protocol) server exposing `capture_memory` and `search_memories` tools.

```text
AI Client → MCP Server → Memory API → (Ollama embeddings) → Postgres (pgvector)
```

## Prerequisites

- Docker + Docker Compose
- Ollama running on the host (default: `http://localhost:11434`)
  - Ensure an embedding model is available, e.g. `ollama pull nomic-embed-text`

## Quick start

```bash
cp .env.example .env
docker compose up -d --build
```

API will be on `http://localhost:8000` and MCP on `http://localhost:8080/mcp`.

## Test memory capture

```bash
curl -sS -X POST http://localhost:8000/capture \
  -H 'Content-Type: application/json' \
  -d '{"content":"example memory","source":"manual"}' | cat
```

## Test semantic search

```bash
curl -sS 'http://localhost:8000/search?query=example&limit=5' | cat
```

## MCP tools

This server implements MCP **Streamable HTTP** at:

- `POST http://localhost:8080/mcp`

Supported MCP methods:
- `initialize`
- `ping`
- `tools/list`
- `tools/call`

Tools:
- `capture_memory` `{ content: string, source?: string }`
- `search_memories` `{ query: string, limit?: number }`

### MCP client integration

#### ChatGPT connectors / HTTP MCP clients

If your client supports MCP **Streamable HTTP**, configure the MCP endpoint URL as:

- `http://localhost:8080/mcp`

#### Claude Desktop (stdio)

Claude Desktop typically runs MCP servers over **stdio** (a local command).
This repo includes a stdio entrypoint inside the MCP Docker image.

Example `claude_desktop_config.json` snippet:

```json
{
  "mcpServers": {
    "synapse": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "-e",
        "API_BASE_URL=http://host.docker.internal:8000",
        "synapse-mcp",
        "python",
        "/app/stdio_server.py"
      ]
    }
  }
}
```

Notes:
- Ensure the Synapse stack is running (`docker compose up -d --build`).
- On Linux, replace `host.docker.internal` with your host IP or another reachable hostname.

## Troubleshooting

### Ollama unreachable from Docker

By default we use `OLLAMA_HOST=host.docker.internal` (works on Docker Desktop). On Linux, set `OLLAMA_HOST` to your host IP (or run Ollama in Docker).

### Embedding dimension mismatch

The database schema uses `VECTOR(768)`. If your embedding model returns a different dimension, `/capture` and `/search` will return a 500 with a clear error. Use a 768-dim model (default `nomic-embed-text`) or adjust the schema + code together.

### Postgres/pgvector init

If you changed the schema and need to re-run init, remove the volume:

```bash
docker compose down -v
```

## License

MIT (see `LICENSE`).
