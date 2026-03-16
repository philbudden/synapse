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
- `MATRIX_PUBLIC_BASE_URL` (recommended): the exact homeserver URL you will type into Element X, e.g. `https://mac-workstation` or `https://mac-workstation.<tailnet>.ts.net`

For best results on iOS, prefer a **hostname** (MagicDNS / .ts.net) on port **443**.

Notes:
- On first start, Synapse generates `homeserver.yaml` into its persistent `/data` volume. If you change `MATRIX_SERVER_NAME` later, wipe the Matrix volume (`docker compose down -v`) to regenerate.
- Registration is enabled by default for **LAN/VPN-only** convenience.

Verify Matrix is up (TLS proxy):

```bash
# Port 443 is published to the proxy by default.
curl -kfsS "https://${MATRIX_PUBLIC_HOST:-localhost}/_matrix/client/versions" | cat
```

### Connect from Element X (LAN/VPN)

Option A (simplest, local-only HTTP):
- Homeserver URL: `http://<host>:8008`
- Example: `http://mac-workstation:8008`

Account creation note (Element X):
- Recent Element X builds may not support **in-app sign up** on classic-password homeservers without a Matrix Authentication Service (MAS).
- Workaround: create the user on the server (command below), then use **Sign in** in Element X.

Option B (HTTPS via TLS proxy):
- Preferred: `https://<host>` (port **443**)
- Alternate: `https://<host>:<MATRIX_TLS_PORT>` (default **8448**)

Examples:
- `https://mac-workstation`
- `https://mac-workstation:8448`

TLS notes:
- By default the proxy uses a local TLS certificate from Caddy’s **internal CA**.
- If iOS shows **“This Connection Is Not Private”**, you must either trust the CA root on the phone or use a publicly-trusted certificate.

If you can’t get Tailscale TLS certs, prefer Option A (HTTP) for LAN-only.

Create a local user (run on the host):

```bash
# creates @alice:<MATRIX_SERVER_NAME> with password
docker compose --profile matrix exec -T matrix-synapse \
  register_new_matrix_user -c /data/homeserver.yaml \
  -u alice -p 'change-me' http://localhost:8008
```

Then in Element X choose **Sign in**, and enter:
- Username: `@alice:${MATRIX_SERVER_NAME}` (default `@alice:localhost`)
- Password: the one you set

If you do have a publicly-trusted cert available, you can configure the proxy like this:

1. On the host, generate a cert for your MagicDNS name:

   ```bash
   tailscale cert mac-workstation.tailXXXX.ts.net
   ```

2. Copy the generated `.crt` and `.key` into `./.local/matrix-tls/`.

3. Set in `.env`:

   ```bash
   MATRIX_PUBLIC_BASE_URL=https://mac-workstation.tailXXXX.ts.net
   MATRIX_TLS_CERT_FILE=/tls/mac-workstation.tailXXXX.ts.net.crt
   MATRIX_TLS_KEY_FILE=/tls/mac-workstation.tailXXXX.ts.net.key
   ```

4. Restart:

   ```bash
   docker compose --profile matrix up -d
   ```

Otherwise (internal CA path), install and trust the CA root certificate on your phone:

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
