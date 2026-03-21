# Synapse Structured Memory -- Implementation Plan

This document is intended for use by an **LLM coding assistant** to implement a structured memeory layer to Synapse.

### Objective

Add a **structured memory layer** alongside the existing PGVector-based memory system.

This layer will:
- Store authoritative, user-curated context (e.g. infrastructure, preferences)
- Be retrieved deterministically (no embeddings)
- Be injected into prompts before LLM responses

This is NOT a replacement for vector memory — it is a complementary system.

---

## High-Level Architecture Changes

Current:

LLM → MCP → API → PGVector (search_memories)

Target:

1. Fetch structured memory (PostgreSQL JSONB)
2. Fetch vector memory (existing search_memories)
3. Combine both
4. Return to LLM

---

## Phase 1 — Database Layer

### 1.1 Create Structured Memory Table

Modify:
`db/init.sql`

Add:

```sql
CREATE TABLE IF NOT EXISTS structured_memory (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW()
);
```

## Phase 2 — API Layer

### 2.1 Add Structured Memory Access

Modify:
```code
api/app/db.py
```

Add function:
```python
def get_structured_memory(key: str):
    query = "SELECT value FROM structured_memory WHERE key = %s"
    result = execute_query(query, (key,))
    return result[0]["value"] if result else None
```

### 2.2 Add API Endpoint

Modify:
```code
api/app/main.py
```

Add endpoint:
```python
@app.get("/structured_memory/{key}")
def fetch_structured_memory(key: str):
    value = get_structured_memory(key)
    if value is None:
        return {"key": key, "value": None}
    return {"key": key, "value": value}
```

## Phase 3 — MCP Server Integration

### 3.1 Add New Tool

Modify:
```code
mcp/server.py
```

```python
{
  "name": "get_structured_memory",
  "description": "Retrieve structured, authoritative user context",
  "parameters": {
    "type": "object",
    "properties": {
      "key": {"type": "string"}
    },
    "required": ["key"]
  }
}
```

### 3.2 Implement Tool Handler
```python
elif tool_name == "get_structured_memory":
    key = arguments["key"]
    response = requests.get(f"{API_URL}/structured_memory/{key}")
    return response.json()
```

## Phase 4 — Prompt Injection Layer (CRITICAL)

This is where most of the value comes from.

### 4.1 Update Tool Usage Pattern

New flow:
- Call get_structured_memory
- Call search_memories
- Combine both before responding

### 4.2 Inject Structured Context into Prompt

Format:
```markdown
## Structured Context (Authoritative)

### Infrastructure
<render JSON as readable text>

### Preferences
<render JSON>

---

## Retrieved Context
<existing vector search results>

---

## User Query
<original query>
```

### 4.3 Add Rendering Function

```python
def render_structured_memory(data: dict) -> str:
    return json.dumps(data, indent=2)
```

---

End of Plan
