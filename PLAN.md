# Synapse Minimal (Local-First) -- Implementation Plan

This document is intended for use by an **LLM coding assistant** to implement a minimal, self-contained "Synapse" system that provides:
- Persistent AI memory
- Vector search over captured thoughts
- A local ingestion + retrieval API
- MCP (Model Context Protocol) tool interface for AI clients
- Container-native deployment

The system is designed so that **any MCP-compatible AI client** (Claude Desktop, ChatGPT connectors, Cursor, etc) can retrieve and store memories.

The implementation should be **simple, robust, and production-friendly** while remaining small enough for a homelab or personal server.

Target runtime environments:
- Docker / Docker Compose
- Kubernetes (optional later)
- Local machine or homelab
- Raspberry Pi cluster

Ollama is assumed to **already be running**, but the system must allow:
- default connection to local Ollama
- configuration of a remote Ollama instance

---

## 1. Project Goals

The system must:
1. Store captured thoughts
2. Generate embeddings for semantic search
3. Store vectors in PostgreSQL using pgvector
4. Allow semantic search over memories
5. Expose capture + search via MCP tools
6. Run entirely in containers except Ollama
7. Be easy for a non-expert to deploy

The system should remain **minimal**.

Target code size:
- `\~300--500 lines Python`

---

## 2. High-Level Architecture

System architecture:
```code
Capture → API → Embeddings → Postgres (pgvector) → MCP → AI Clients
```

Diagram:
```code
    AI Client (ChatGPT / Claude / Cursor)
                │
                ▼
           MCP Server
                │
                ▼
           Memory API
                │
        ┌───────┴────────┐
        ▼                ▼
    Embeddings        Database
      (Ollama)      PostgreSQL + pgvector
```

### Responsibilities:

API Service
- capture memories
- generate embeddings
- store memories
- run semantic search

Database
- persistent storage
- vector similarity search

MCP Server
- expose memory tools to AI clients

---

## 3. Technology Stack

- Language: Python 3.11+
- Framework: FastAPI
- Database: PostgreSQL 15+ with pgvector
- Container Runtime: Docker
- Embeddings: Ollama
- Vector Extension: pgvector

---

## 4. Repository Structure

The project should generate the following layout:
```code
synapse/
│
├── docker-compose.yml
├── .env.example
├── README.md
├── PLAN.md
│
├── db/
│   └── init.sql
│
├── api/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── __init__.py
│       ├── main.py
│       ├── config.py
│       ├── db.py
│       ├── embeddings.py
│       ├── models.py
│       └── search.py
│
├── mcp/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── server.py
│
└── docs/
    └── architecture.md
```

---

## 5. Environment Variables

The system must use environment variables.

Required variables:
- POSTGRES_HOST
- POSTGRES_PORT
- POSTGRES_DB
- POSTGRES_USER
- POSTGRES_PASSWORD
- OLLAMA_HOST
- OLLAMA_PORT
- EMBED_MODEL

Defaults:
- OLLAMA_HOST=host.docker.internal OLLAMA_PORT=11434
- EMBED_MODEL=nomic-embed-text

Users must be able to override these values.

---

## 6. Database Schema

Create PostgreSQL schema with pgvector enabled.

SQL:
```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

Captures table:
```sql
CREATE TABLE captures (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source TEXT,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

Memories table:
```sql
CREATE TABLE memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    capture_id UUID REFERENCES captures(id),
    content TEXT NOT NULL,
    embedding VECTOR(768)
);
```

Index:
```sql
CREATE INDEX memories_embedding_idx
ON memories
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
```

---

## 7. API Service Requirements

The API must be implemented using **FastAPI**.

### Endpoint: Capture Memory

**POST** `/capture`

Stores a new memory and generates its embedding.

#### Request Body

```json
{
  "content": "string",
  "source": "optional string"
}
```

#### Processing Steps

1. Store the capture in the `captures` table.
2. Generate an embedding using Ollama.
3. Store the memory and embedding in the `memories` table.

#### Response

```json
{
  "status": "stored",
  "id": "uuid"
}
```

### Endpoint: Semantic Search

**GET** `/search`

Performs semantic search over stored memories.

#### Query Parameters

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| query | string | Search text to embed and compare | required |
| limit | integer | Maximum results to return | 5 |

#### Processing Steps

1. Generate an embedding for the `query` using Ollama.
2. Perform a vector similarity search against stored embeddings.
3. Rank results by cosine similarity.
4. Return the top results.

#### Response

```json
{
  "results": [
    {
      "content": "...",
      "score": 0.82
    }
  ]
}
```

---

## 8. Ollama Integration

Embeddings should be generated via the **Ollama HTTP API**.

### Endpoint

**POST** `/api/embeddings`

### Example Request

```json
{
  "model": "nomic-embed-text",
  "prompt": "example text"
}
```

### Requirements

The API must support:
- Local Ollama instance
- Remote Ollama instance

Connection details must be configurable via **environment variables**.

### Error Handling

- Timeouts must be handled gracefully.
- If Ollama is unreachable, the API should return a clear error response.

---

## 9. MCP Server

The MCP server exposes two tools for AI clients.

### Tool: `capture_memory`

#### Arguments

| Argument | Type | Description |
|--------|------|-------------|
| content | string | Memory content to store |
| source | string | Optional origin of the memory |

#### Implementation

Calls the API endpoint:

```
POST /capture
```

---

### Tool: `search_memories`

#### Arguments

| Argument | Type | Description |
|--------|------|-------------|
| query | string | Semantic search query |
| limit | integer | Maximum results to return |

#### Implementation

Calls the API endpoint:

```
GET /search
```

---

## 10. Docker Compose

Docker Compose should start the following services:

- `postgres`
- `api`
- `mcp`

### Example Service Definitions

```yaml
services:

  postgres:
    image: pgvector/pgvector:pg15

  api:
    build: ./api

  mcp:
    build: ./mcp
```

### Volumes

```
postgres_data
```

### Ports

| Service | Port |
|-------|------|
| api | 8000 |
| mcp | 8080 |

---

## 11. README Requirements

The generated repository **must include a clear `README.md`**.

### README Must Include

- Project description
- Architecture diagram
- Prerequisites
- Deployment instructions
- Troubleshooting

### Prerequisites

- Docker installed
- Ollama running

---

### Quick Start Guide

1. Clone the repository
2. Copy the environment template

```
cp .env.example .env
```

3. Start the system

```
docker compose up -d
```

---

### Test Memory Capture

```
curl -X POST localhost:8000/capture \
  -H "Content-Type: application/json" \
  -d '{"content": "example memory"}'
```

---

### Test Semantic Search

```
curl "localhost:8000/search?query=test"
```

---

### MCP Client Integration

Provide example MCP configuration for:

- Claude Desktop
- ChatGPT connectors
- Other MCP-compatible clients

---

## 12. Development Principles

The coding assistant should follow these principles:

- Prefer **simplicity over abstraction**
- Avoid heavy frameworks
- Use small, clear modules
- Include **type hints**
- Include **docstrings**
- Handle failures gracefully
- Keep the implementation **minimal and readable**

---

## 13. Future Extensions (Not Required)

The following features **should not be implemented initially**, but the architecture should allow them later:

- Entity extraction
- Knowledge graph generation
- Matrix/Slack capture bot
- Background summarisation
- Multi-user authentication
- External document ingestion

---

## 14. Acceptance Criteria

The project is considered complete when:

- Docker Compose starts successfully
- User can capture a memory
- User can perform semantic search over stored memories
- Embeddings are generated through Ollama
- MCP tools work with an AI client
- The README allows a user to deploy the project within **10 minutes**

---

End of Plan
