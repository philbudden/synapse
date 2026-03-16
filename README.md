# Synapse

Synapse is a **personal memory inbox** you can talk to.

- You write a thought.
- Synapse stores it in a database.
- Later you can search it by meaning (semantic search).

This repo runs everything in Docker **except Ollama** (embeddings), which you run separately.

## What you’ll run

- **Ollama** (on your machine or a remote host) — creates embeddings
- **Synapse API** (Docker) — stores and searches memories
- **Postgres** (Docker) — database
- **Synapse MCP server** (Docker) — lets LLM clients use Synapse as tools
- **Matrix homeserver (Synapse)** (Docker, optional) — so you can capture memories from Element X
- **Matrix capture bot** (Docker, optional) — turns Matrix room messages into stored memories

---

## Prerequisites

1. Install **Docker Desktop** (or Docker Engine + Compose).
2. Install **Ollama**.
3. Ensure the embedding model exists:

```bash
ollama pull nomic-embed-text
```

If you want to use a **remote Ollama** (example: `100.104.36.96`): set `OLLAMA_HOST` in `.env` (steps below).

---

## 1) Start Synapse (API + DB + MCP)

### Step 1 — Create your config

```bash
cp .env.example .env
```

Edit `.env` if needed:

- Local Ollama (default on macOS/Windows Docker Desktop):
  - `OLLAMA_HOST=host.docker.internal`
  - `OLLAMA_PORT=11434`
- Remote Ollama example:
  - `OLLAMA_HOST=100.104.36.96`
  - `OLLAMA_PORT=11434`

### Step 2 — Start the stack

```bash
docker compose up -d --build
```

### Step 3 — Verify it’s running

```bash
curl -fsS http://localhost:8000/health | cat
curl -fsS http://localhost:8080/health | cat
```

You should have:

- API: `http://localhost:8000`
- MCP: `http://localhost:8080/mcp`

### Step 4 — Quick API test (optional)

Capture a memory:

```bash
curl -sS -X POST http://localhost:8000/capture \
  -H 'Content-Type: application/json' \
  -d '{"content":"buy better coffee beans"}' | cat
```

Search:

```bash
curl -sS 'http://localhost:8000/search?query=coffee&limit=5' | cat
```

---

## 2) Capture memories using Matrix (Element X)

This repo can run a full Matrix homeserver (Synapse) in Docker.

### Important note about Element X “Sign up”

Many Element X builds **won’t create accounts** on classic-password homeservers unless you add Matrix Authentication Service (MAS).

This setup is still usable:

- Create users **on the server** (one-time command)
- Then use **Sign in** in Element X

### Step 1 — Start Matrix services

```bash
docker compose --profile matrix up -d --build
```

Matrix will be available locally at:

- `http://localhost:8008`

### Step 2 — Create your Matrix user

Replace `alice` / password as you like:

```bash
docker compose --profile matrix exec -T matrix-synapse \
  register_new_matrix_user -c /data/homeserver.yaml \
  -u alice -p 'change-me' http://localhost:8008
```

### Step 3 — Connect from Element X (recommended: HTTP for LAN/VPN)

On your phone (same home network / VPN / Tailscale):

1. Open Element X
2. Choose **Sign in** (not Sign up)
3. Homeserver:
   - `http://<your-mac-or-server-hostname>:8008`
   - Example: `http://mac-workstation:8008`
4. Username:
   - `@alice:<MATRIX_SERVER_NAME>` (default `@alice:localhost`)
5. Password:
   - the one you set

### Step 4 — Turn Matrix messages into stored memories (Matrix bot)

The `matrix-bot` service watches **one room** and stores every message as a memory.

#### 4a) Create a bot user

```bash
docker compose --profile matrix exec -T matrix-synapse \
  register_new_matrix_user -c /data/homeserver.yaml \
  -u synapsebot -p 'bot-password' http://localhost:8008
```

#### 4b) Get the bot access token

Run on your host:

```bash
curl -sS -X POST http://localhost:8008/_matrix/client/v3/login \
  -H 'Content-Type: application/json' \
  -d '{"type":"m.login.password","user":"synapsebot","password":"bot-password"}' | cat
```

If login fails, try the full Matrix ID as the user:

```bash
curl -sS -X POST http://localhost:8008/_matrix/client/v3/login \
  -H 'Content-Type: application/json' \
  -d '{"type":"m.login.password","user":"@synapsebot:localhost","password":"bot-password"}' | cat
```

Copy the `access_token` from the response.

#### 4c) Create a room (your “inbox”) and get its Room ID

1. Create a room (e.g. “Synapse Inbox”)

Element X doesn’t always show the raw **Room ID** in the UI. You can fetch it from the homeserver.

First, log in to the homeserver as your normal user (replace username/password):

```bash
curl -sS --max-time 10 -X POST http://localhost:8008/_matrix/client/v3/login \
  -H 'Content-Type: application/json' \
  -d '{"type":"m.login.password","user":"alice","password":"change-me"}'
```

From that JSON response, copy the `access_token`.

Now list the rooms you’ve joined — the returned values are **Room IDs**:

- If you have `jq` installed:

```bash
curl -sS --max-time 10 http://localhost:8008/_matrix/client/v3/joined_rooms \
  -H "Authorization: Bearer <PASTE_ACCESS_TOKEN>" \
| jq -r '.joined_rooms[]'
```

- No `jq` installed (uses Python):

```bash
curl -sS --max-time 10 http://localhost:8008/_matrix/client/v3/joined_rooms \
  -H "Authorization: Bearer <PASTE_ACCESS_TOKEN>" \
| python3 -c 'import sys,json; print("\n".join(json.load(sys.stdin)["joined_rooms"]))'
```

Tip: send a message in your “Synapse Inbox” room first, then run the command — it’ll be easier to identify the right room.

#### 4d) Configure + start the bot

Set these in `.env` (replace the room ID and token):

```text
MATRIX_HOMESERVER=http://matrix-synapse:8008
MATRIX_USER_ID=@synapsebot:localhost
MATRIX_ACCESS_TOKEN=PASTE_TOKEN_HERE
MATRIX_ROOM_ID=!yourRoomId:localhost
```

Restart the bot:

```bash
docker compose --profile matrix up -d --build matrix-bot
```

Note: the bot can only accept invites when it’s running and has `MATRIX_USER_ID` + `MATRIX_ACCESS_TOKEN` configured.

#### 4e) Invite the bot to the room

In Element X, invite `@synapsebot:<MATRIX_SERVER_NAME>` to the room.

- If you already invited it earlier: after the bot is configured and restarted, it should accept automatically within ~30 seconds.
- If it stays stuck under “Invited”, check the bot logs:

```bash
docker compose --profile matrix logs --tail=200 matrix-bot
```

#### 4f) Test

Post a message in the room. The bot should reply with the stored memory ID (and category).

---

## 3) Connect Synapse MCP to other LLM services

Synapse exposes MCP **Streamable HTTP** at:

- `http://localhost:8080/mcp`

The MCP server provides two tools:

- `capture_memory` — store a memory
- `search_memories` — semantic search

### Option A — Use an HTTP MCP client

If your client supports **HTTP MCP**, point it at:

- `http://localhost:8080/mcp`

### Option B — Claude Desktop (stdio)

Claude Desktop uses MCP over a local command. This repo ships a stdio entrypoint inside the MCP Docker image.

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
- Ensure the stack is running (`docker compose up -d --build`).
- On Linux, replace `host.docker.internal` with your host IP/hostname.

---

## Troubleshooting

### API says Ollama is unavailable

- Confirm Ollama is running.
- Confirm the API container can reach it:
  - macOS/Windows: `OLLAMA_HOST=host.docker.internal`
  - remote: set `OLLAMA_HOST=<ip/hostname>`

### Element X can’t connect

- Prefer HTTP for local-only: `http://<host>:8008`
- Make sure you used **Sign in**, and created the user with `register_new_matrix_user`.

### Matrix bot is “idling”

This means it isn’t configured yet. Set:

- `MATRIX_USER_ID`
- `MATRIX_ACCESS_TOKEN`
- `MATRIX_ROOM_ID`

Then restart the bot:

```bash
docker compose --profile matrix up -d matrix-bot
```

---

## License

MIT (see `LICENSE`).
