from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
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


@dataclass
class _Session:
    queue: asyncio.Queue[str]
    last_activity: float


_SESSIONS: dict[str, _Session] = {}
_SESSIONS_LOCK = asyncio.Lock()
_SSE_KEEPALIVE_SECONDS = 15
_SESSION_TTL_SECONDS = 60 * 60


def _sse_message(payload: dict[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False)
    return f"event: message\ndata: {data}\n\n"


async def _create_session() -> str:
    session_id = str(uuid.uuid4())
    async with _SESSIONS_LOCK:
        _SESSIONS[session_id] = _Session(queue=asyncio.Queue(), last_activity=time.time())
    return session_id


async def _get_session(session_id: str) -> _Session | None:
    async with _SESSIONS_LOCK:
        s = _SESSIONS.get(session_id)
        if s is None:
            return None
        if time.time() - s.last_activity > _SESSION_TTL_SECONDS:
            _SESSIONS.pop(session_id, None)
            return None
        return s


async def _touch_session(session_id: str) -> None:
    async with _SESSIONS_LOCK:
        s = _SESSIONS.get(session_id)
        if s is not None:
            s.last_activity = time.time()


async def _delete_session(session_id: str) -> None:
    async with _SESSIONS_LOCK:
        _SESSIONS.pop(session_id, None)


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


def _render_structured_memory(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False)


def _format_combined_context(
    structured: dict[str, Any],
    retrieved: dict[str, Any],
    query: str,
) -> str:
    lines: list[str] = ["## Structured Context (Authoritative)"]

    key = structured.get("key")
    value = structured.get("value")
    if key:
        lines.append("")
        lines.append(f"### {key}")
        if value is None:
            lines.append("(none)")
        else:
            lines.append(_render_structured_memory(value))
    else:
        lines.append("")
        lines.append("(none)")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Retrieved Context")
    lines.append(_render_structured_memory(retrieved))
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## User Query")
    lines.append(query)
    return "\n".join(lines)


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


async def _api_get_structured_memory(key: str) -> dict[str, Any]:
    url = f"{settings.api_base_url}/structured_memory/{key}"

    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0)) as client:
        resp = await client.get(url)
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
    {
        "name": "get_structured_memory",
        "title": "Get Structured Memory",
        "description": "Retrieve structured, authoritative user context.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Structured memory key"},
            },
            "required": ["key"],
        },
    },
    {
        "name": "get_context",
        "title": "Get Combined Context",
        "description": "Combine structured memory and semantic search for prompt injection.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Structured memory key"},
                "query": {"type": "string", "description": "Semantic search query"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 5},
            },
            "required": ["key", "query"],
        },
    },
]


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/mcp/openapi.json")
async def mcp_openapi() -> JSONResponse:
    # Some clients probe for this under the MCP path.
    return JSONResponse(app.openapi())


@app.get("/mcp")
async def mcp_get(origin: str | None = Header(default=None)) -> Response:
    if not _origin_allowed(origin):
        raise HTTPException(status_code=403, detail="Origin not allowed")

    session_id = await _create_session()

    async def event_stream():
        try:
            while True:
                s = await _get_session(session_id)
                if s is None:
                    return
                try:
                    msg = await asyncio.wait_for(s.queue.get(), timeout=_SSE_KEEPALIVE_SECONDS)
                    await _touch_session(session_id)
                    yield msg
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            await _delete_session(session_id)

    headers = {
        "MCP-Session-Id": session_id,
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=headers)


@app.delete("/mcp")
async def mcp_delete(
    origin: str | None = Header(default=None),
    mcp_session_id: str | None = Header(default=None, alias="MCP-Session-Id"),
) -> Response:
    if not _origin_allowed(origin):
        raise HTTPException(status_code=403, detail="Origin not allowed")
    if not mcp_session_id:
        raise HTTPException(status_code=400, detail="Missing MCP-Session-Id")
    await _delete_session(mcp_session_id)
    return Response(status_code=204)


@app.post("/mcp")
async def mcp_post(
    request: Request,
    origin: str | None = Header(default=None),
    accept: str | None = Header(default=None),
    mcp_protocol_version: str | None = Header(default=None, alias="MCP-Protocol-Version"),
    mcp_session_id: str | None = Header(default=None, alias="MCP-Session-Id"),
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

    async def _deliver(payload: dict[str, Any], status_code: int = 200) -> Response:
        if mcp_session_id:
            s = await _get_session(mcp_session_id)
            if s is None:
                err = _jsonrpc_error(payload.get("id"), -32000, "Unknown or expired MCP session")
                return Response(status_code=400, content=json.dumps(err), media_type="application/json")
            await _touch_session(mcp_session_id)
            await s.queue.put(_sse_message(payload))
            return Response(status_code=202)

        return Response(status_code=status_code, content=json.dumps(payload), media_type="application/json")

    try:
        if method == "ping":
            payload = _jsonrpc_result(request_id, {})
            return await _deliver(payload)

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
                    "description": "MCP server exposing persistent memory capture, search, and structured context.",
                },
                "instructions": "Use capture_memory to store memories, search_memories to retrieve related ones, and get_context for combined prompt context.",
            }
            payload = _jsonrpc_result(request_id, result)
            return await _deliver(payload)

        if method == "tools/list":
            payload = _jsonrpc_result(request_id, {"tools": TOOLS, "nextCursor": None})
            return await _deliver(payload)

        if method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments") or {}
            if not isinstance(name, str) or not name:
                payload = _jsonrpc_error(request_id, -32602, "Invalid params", "name is required")
                return await _deliver(payload)
            if not isinstance(arguments, dict):
                payload = _jsonrpc_error(request_id, -32602, "Invalid params", "arguments must be an object")
                return await _deliver(payload)

            if name == "capture_memory":
                content = arguments.get("content")
                source = arguments.get("source")
                if not isinstance(content, str) or not content.strip():
                    result = {"content": [{"type": "text", "text": "content is required"}], "isError": True}
                    return await _deliver(_jsonrpc_result(request_id, result))
                if source is not None and not isinstance(source, str):
                    result = {"content": [{"type": "text", "text": "source must be a string"}], "isError": True}
                    return await _deliver(_jsonrpc_result(request_id, result))

                try:
                    api_res = await _api_capture(content.strip(), source)
                except httpx.HTTPError as e:
                    result = {"content": [{"type": "text", "text": f"API error calling /capture: {e}"}], "isError": True}
                    return await _deliver(_jsonrpc_result(request_id, result))

                text = f"Stored memory id={api_res.get('id')}"
                result = {"content": [{"type": "text", "text": text}], "structuredContent": api_res, "isError": False}
                return await _deliver(_jsonrpc_result(request_id, result))

            if name == "search_memories":
                query = arguments.get("query")
                limit = arguments.get("limit", 5)
                if not isinstance(query, str) or not query.strip():
                    result = {"content": [{"type": "text", "text": "query is required"}], "isError": True}
                    return await _deliver(_jsonrpc_result(request_id, result))
                if not isinstance(limit, int):
                    result = {"content": [{"type": "text", "text": "limit must be an integer"}], "isError": True}
                    return await _deliver(_jsonrpc_result(request_id, result))

                try:
                    api_res = await _api_search(query.strip(), limit)
                except httpx.HTTPError as e:
                    result = {"content": [{"type": "text", "text": f"API error calling /search: {e}"}], "isError": True}
                    return await _deliver(_jsonrpc_result(request_id, result))

                # Provide both unstructured and structured for maximum client compatibility.
                text = json.dumps(api_res, ensure_ascii=False)
                result = {"content": [{"type": "text", "text": text}], "structuredContent": api_res, "isError": False}
                return await _deliver(_jsonrpc_result(request_id, result))

            if name == "get_structured_memory":
                key = arguments.get("key")
                if not isinstance(key, str) or not key.strip():
                    result = {"content": [{"type": "text", "text": "key is required"}], "isError": True}
                    return await _deliver(_jsonrpc_result(request_id, result))

                try:
                    api_res = await _api_get_structured_memory(key.strip())
                except httpx.HTTPError as e:
                    result = {
                        "content": [{"type": "text", "text": f"API error calling /structured_memory: {e}"}],
                        "isError": True,
                    }
                    return await _deliver(_jsonrpc_result(request_id, result))

                text = json.dumps(api_res, ensure_ascii=False)
                result = {
                    "content": [{"type": "text", "text": text}],
                    "structuredContent": api_res,
                    "isError": False,
                }
                return await _deliver(_jsonrpc_result(request_id, result))

            if name == "get_context":
                query = arguments.get("query")
                limit = arguments.get("limit", 5)
                key = arguments.get("key")
                if not isinstance(query, str) or not query.strip():
                    result = {"content": [{"type": "text", "text": "query is required"}], "isError": True}
                    return await _deliver(_jsonrpc_result(request_id, result))
                if not isinstance(limit, int):
                    result = {"content": [{"type": "text", "text": "limit must be an integer"}], "isError": True}
                    return await _deliver(_jsonrpc_result(request_id, result))
                if not isinstance(key, str) or not key.strip():
                    result = {"content": [{"type": "text", "text": "key is required"}], "isError": True}
                    return await _deliver(_jsonrpc_result(request_id, result))

                try:
                    structured_res, search_res = await asyncio.gather(
                        _api_get_structured_memory(key.strip()),
                        _api_search(query.strip(), limit),
                    )
                except httpx.HTTPError as e:
                    result = {"content": [{"type": "text", "text": f"API error building context: {e}"}], "isError": True}
                    return await _deliver(_jsonrpc_result(request_id, result))

                combined = _format_combined_context(structured_res, search_res, query.strip())
                structured_payload = {
                    "structured": structured_res,
                    "retrieved": search_res,
                    "combined": combined,
                }
                result = {
                    "content": [{"type": "text", "text": combined}],
                    "structuredContent": structured_payload,
                    "isError": False,
                }
                return await _deliver(_jsonrpc_result(request_id, result))

            payload = _jsonrpc_error(request_id, -32602, "Unknown tool", {"name": name})
            return await _deliver(payload)

        payload = _jsonrpc_error(request_id, -32601, "Method not found", {"method": method})
        return await _deliver(payload)

    except Exception as e:
        payload = _jsonrpc_error(request_id, -32603, "Internal error", str(e))
        return await _deliver(payload)
