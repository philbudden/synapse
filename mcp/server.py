from __future__ import annotations

import json
from typing import Any, Literal

import httpx
from fastapi import FastAPI, Header, HTTPException, Request, Response
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    api_base_url: str = "http://api:8000"
    mcp_allowed_origins: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def allowed_origins(self) -> set[str]:
        return {o.strip() for o in self.mcp_allowed_origins.split(",") if o.strip()}


settings = Settings()

SUPPORTED_PROTOCOL_VERSIONS = ["2025-11-25", "2025-03-26"]

app = FastAPI(title="Synapse MCP", version="0.1.0")


def _origin_allowed(origin: str | None) -> bool:
    if origin is None:
        return True
    allowed = settings.allowed_origins
    if not allowed:
        return False
    return origin in allowed


def _jsonrpc_error(
    request_id: Any | None,
    code: int,
    message: str,
    data: Any | None = None,
) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data

    payload: dict[str, Any] = {"jsonrpc": "2.0", "error": err}
    if request_id is not None:
        payload["id"] = request_id
    return payload


def _jsonrpc_result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _require_request(msg: dict[str, Any]) -> tuple[Any, str, dict[str, Any]]:
    if msg.get("jsonrpc") != "2.0":
        raise ValueError("jsonrpc must be '2.0'")
    if "id" not in msg:
        raise ValueError("missing id")
    method = msg.get("method")
    if not isinstance(method, str) or not method:
        raise ValueError("missing method")
    params = msg.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise ValueError("params must be an object")
    return msg["id"], method, params


async def _api_capture(content: str, source: str | None) -> dict[str, Any]:
    url = f"{settings.api_base_url}/capture"
    payload: dict[str, Any] = {"content": content}
    if source is not None:
        payload["source"] = source

    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0)) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()


async def _api_search(query: str, limit: int) -> dict[str, Any]:
    url = f"{settings.api_base_url}/search"
    params = {"query": query, "limit": limit}

    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0)) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


TOOLS: list[dict[str, Any]] = [
    {
        "name": "capture_memory",
        "title": "Capture Memory",
        "description": "Store a memory in Synapse and generate an embedding via Ollama.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Memory content to store"},
                "source": {"type": "string", "description": "Optional origin of the memory"},
            },
            "required": ["content"],
        },
    },
    {
        "name": "search_memories",
        "title": "Search Memories",
        "description": "Semantic search over stored memories using pgvector cosine similarity.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Semantic search query"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 5},
            },
            "required": ["query"],
        },
    },
]


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/mcp")
async def mcp_get(origin: str | None = Header(default=None)) -> Response:
    if not _origin_allowed(origin):
        raise HTTPException(status_code=403, detail="Origin not allowed")
    # Minimal server: we don't support a standalone SSE stream.
    return Response(status_code=405)


@app.delete("/mcp")
async def mcp_delete(origin: str | None = Header(default=None)) -> Response:
    if not _origin_allowed(origin):
        raise HTTPException(status_code=403, detail="Origin not allowed")
    return Response(status_code=405)


@app.post("/mcp")
async def mcp_post(
    request: Request,
    origin: str | None = Header(default=None),
    accept: str | None = Header(default=None),
    mcp_protocol_version: str | None = Header(default=None, alias="MCP-Protocol-Version"),
) -> Response:
    if not _origin_allowed(origin):
        raise HTTPException(status_code=403, detail="Origin not allowed")

    # If provided, validate MCP-Protocol-Version header.
    if mcp_protocol_version is not None and mcp_protocol_version not in SUPPORTED_PROTOCOL_VERSIONS:
        raise HTTPException(status_code=400, detail="Unsupported MCP-Protocol-Version")

    body = await request.body()
    try:
        msg = json.loads(body.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Notifications / responses: accept and return 202.
    if isinstance(msg, dict) and "id" not in msg:
        return Response(status_code=202)

    if not isinstance(msg, dict):
        return Response(status_code=400, content=json.dumps(_jsonrpc_error(None, -32600, "Invalid Request")), media_type="application/json")

    try:
        request_id, method, params = _require_request(msg)
    except ValueError as e:
        return Response(
            status_code=400,
            content=json.dumps(_jsonrpc_error(msg.get("id"), -32600, "Invalid Request", str(e))),
            media_type="application/json",
        )

    try:
        if method == "ping":
            payload = _jsonrpc_result(request_id, {})
            return Response(content=json.dumps(payload), media_type="application/json")

        if method == "initialize":
            requested = params.get("protocolVersion")
            if isinstance(requested, str) and requested in SUPPORTED_PROTOCOL_VERSIONS:
                chosen = requested
            else:
                chosen = SUPPORTED_PROTOCOL_VERSIONS[0]

            result = {
                "protocolVersion": chosen,
                "capabilities": {
                    "tools": {"listChanged": False},
                },
                "serverInfo": {
                    "name": "synapse-mcp",
                    "title": "Synapse MCP",
                    "version": "0.1.0",
                    "description": "MCP server exposing persistent memory capture and semantic search.",
                },
                "instructions": "Use capture_memory to store memories and search_memories to retrieve related ones.",
            }
            payload = _jsonrpc_result(request_id, result)
            return Response(content=json.dumps(payload), media_type="application/json")

        if method == "tools/list":
            payload = _jsonrpc_result(request_id, {"tools": TOOLS, "nextCursor": None})
            return Response(content=json.dumps(payload), media_type="application/json")

        if method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments") or {}
            if not isinstance(name, str) or not name:
                payload = _jsonrpc_error(request_id, -32602, "Invalid params", "name is required")
                return Response(content=json.dumps(payload), media_type="application/json")
            if not isinstance(arguments, dict):
                payload = _jsonrpc_error(request_id, -32602, "Invalid params", "arguments must be an object")
                return Response(content=json.dumps(payload), media_type="application/json")

            if name == "capture_memory":
                content = arguments.get("content")
                source = arguments.get("source")
                if not isinstance(content, str) or not content.strip():
                    result = {"content": [{"type": "text", "text": "content is required"}], "isError": True}
                    return Response(content=json.dumps(_jsonrpc_result(request_id, result)), media_type="application/json")
                if source is not None and not isinstance(source, str):
                    result = {"content": [{"type": "text", "text": "source must be a string"}], "isError": True}
                    return Response(content=json.dumps(_jsonrpc_result(request_id, result)), media_type="application/json")

                try:
                    api_res = await _api_capture(content.strip(), source)
                except httpx.HTTPError as e:
                    result = {"content": [{"type": "text", "text": f"API error calling /capture: {e}"}], "isError": True}
                    return Response(content=json.dumps(_jsonrpc_result(request_id, result)), media_type="application/json")

                text = f"Stored memory id={api_res.get('id')}"
                result = {"content": [{"type": "text", "text": text}], "structuredContent": api_res, "isError": False}
                return Response(content=json.dumps(_jsonrpc_result(request_id, result)), media_type="application/json")

            if name == "search_memories":
                query = arguments.get("query")
                limit = arguments.get("limit", 5)
                if not isinstance(query, str) or not query.strip():
                    result = {"content": [{"type": "text", "text": "query is required"}], "isError": True}
                    return Response(content=json.dumps(_jsonrpc_result(request_id, result)), media_type="application/json")
                if not isinstance(limit, int):
                    result = {"content": [{"type": "text", "text": "limit must be an integer"}], "isError": True}
                    return Response(content=json.dumps(_jsonrpc_result(request_id, result)), media_type="application/json")

                try:
                    api_res = await _api_search(query.strip(), limit)
                except httpx.HTTPError as e:
                    result = {"content": [{"type": "text", "text": f"API error calling /search: {e}"}], "isError": True}
                    return Response(content=json.dumps(_jsonrpc_result(request_id, result)), media_type="application/json")

                # Provide both unstructured and structured for maximum client compatibility.
                text = json.dumps(api_res, ensure_ascii=False)
                result = {"content": [{"type": "text", "text": text}], "structuredContent": api_res, "isError": False}
                return Response(content=json.dumps(_jsonrpc_result(request_id, result)), media_type="application/json")

            payload = _jsonrpc_error(request_id, -32602, "Unknown tool", {"name": name})
            return Response(content=json.dumps(payload), media_type="application/json")

        payload = _jsonrpc_error(request_id, -32601, "Method not found", {"method": method})
        return Response(content=json.dumps(payload), media_type="application/json")

    except Exception as e:
        payload = _jsonrpc_error(request_id, -32603, "Internal error", str(e))
        return Response(content=json.dumps(payload), media_type="application/json")
