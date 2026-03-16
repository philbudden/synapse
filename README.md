# :brain: Synapse

Persistent AI memory: capture thoughts, generate embeddings with Ollama, store in Postgres (pgvector), and retrieve via semantic search. Includes an MCP (Model Context Protocol) server exposing `capture_memory` and `search_memories` tools.

```text
AI Client → MCP Server → Memory API → (Ollama embeddings) → Postgres (pgvector)
```

## Prerequisites

- Docker + Docker Compose
- Ollama reachable from the API container (default: `http://localhost:11434` via `host.docker.internal`)
  - Ensure an embedding model is available, e.g. `ollama pull nomic-embed-text`
  - To use a remote Ollama instance, set `OLLAMA_HOST` (e.g. `100.104.36.96`) and `OLLAMA_PORT` in `.env`

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

Notes:
- `/capture` also returns a `classification` object (category + confidence).
- `/search` results may include `classification` metadata when available.

## Matrix (optional, in-stack homeserver)

This repo can run a full **Matrix Synapse** homeserver in the stack (plus a small TLS proxy so **Element X** can connect over HTTPS) and an optional Matrix bot that captures room messages into Synapse.

Start Matrix services:

```bash
docker compose --profile matrix up -d --build
```

Configure these in `.env`:
- `MATRIX_SERVER_NAME` (domain used in Matrix IDs, e.g. `localhost`)
- `MATRIX_TLS_PORT` (default `8448`)

You can connect from Element X using **either** your LAN IP or Tailnet IP:
- `https://<lan-ip>:8448` or `https://<tailnet-ip>:8448`

Notes:
- On first start, Synapse generates `homeserver.yaml` into its persistent `/data` volume. If you change `MATRIX_SERVER_NAME` later, wipe the Matrix volume (`docker compose down -v`) to regenerate.
- Registration is enabled by default for **LAN/VPN-only** convenience.

Verify Matrix is up (TLS proxy):

```bash
curl -kfsS "https://${MATRIX_PUBLIC_HOST:-localhost}:${MATRIX_TLS_PORT:-8448}/_matrix/client/versions" | cat
```

### Connect from Element X (LAN/VPN)

Use this homeserver URL:

- Preferred (default): `https://<host>` (port **443**)
- Alternate: `https://<host>:<MATRIX_TLS_PORT>` (default **8448**)

Examples:
- `https://mac-workstation` (Tailnet/LAN name)
- `https://mac-workstation:8448`

This uses a local TLS certificate from Caddy’s **internal CA**. To avoid certificate warnings, install and trust the CA root certificate on your phone:

1. Find the proxy container name:

   ```bash
   docker compose --profile matrix ps
   ```

2. Copy the CA cert out (path inside container: `/data/pki/authorities/local/root.crt`):

   ```bash
   docker cp <matrix-proxy-container>:/data/pki/authorities/local/root.crt ./matrix-root.crt
   ```

3. Install `matrix-root.crt` on your phone and mark it as trusted (platform-specific).

Security note: this Matrix setup is intended for **home network / VPN only**. Don’t expose it to the public internet as-is.

### Matrix capture bot (optional)

If you want room messages automatically stored in Synapse, set in `.env`:
- `MATRIX_HOMESERVER` (default `http://matrix-synapse:8008`)
- `MATRIX_USER_ID`
- `MATRIX_ACCESS_TOKEN`
- `MATRIX_ROOM_ID`

Then post a message in the configured room — the bot will store it and reply with the stored ID + category.

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
