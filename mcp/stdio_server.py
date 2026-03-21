from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

import httpx

from server import (
    SUPPORTED_PROTOCOL_VERSIONS,
    TOOLS,
    _api_capture,
    _api_get_structured_memory,
    _api_search,
    _format_combined_context,
    _jsonrpc_error,
    _jsonrpc_result,
    _require_request,
)


async def _handle_request(msg: dict[str, Any]) -> dict[str, Any] | None:
    # Notifications have no id and should not receive a response.
    if "id" not in msg:
        return None

    try:
        request_id, method, params = _require_request(msg)
    except ValueError as e:
        return _jsonrpc_error(msg.get("id"), -32600, "Invalid Request", str(e))

    if method == "ping":
        return _jsonrpc_result(request_id, {})

    if method == "initialize":
        requested = params.get("protocolVersion")
        if isinstance(requested, str) and requested in SUPPORTED_PROTOCOL_VERSIONS:
            chosen = requested
        else:
            chosen = SUPPORTED_PROTOCOL_VERSIONS[0]

        result = {
            "protocolVersion": chosen,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {
                "name": "synapse-mcp",
                "title": "Synapse MCP",
                "version": "0.1.0",
                "description": "MCP server exposing persistent memory capture and semantic search.",
            },
            "instructions": "Use capture_memory to store memories and search_memories to retrieve related ones.",
        }
        return _jsonrpc_result(request_id, result)

    if method == "tools/list":
        return _jsonrpc_result(request_id, {"tools": TOOLS, "nextCursor": None})

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}

        if not isinstance(name, str) or not name:
            return _jsonrpc_error(request_id, -32602, "Invalid params", "name is required")
        if not isinstance(arguments, dict):
            return _jsonrpc_error(request_id, -32602, "Invalid params", "arguments must be an object")

        if name == "capture_memory":
            content = arguments.get("content")
            source = arguments.get("source")
            if not isinstance(content, str) or not content.strip():
                result = {"content": [{"type": "text", "text": "content is required"}], "isError": True}
                return _jsonrpc_result(request_id, result)
            if source is not None and not isinstance(source, str):
                result = {"content": [{"type": "text", "text": "source must be a string"}], "isError": True}
                return _jsonrpc_result(request_id, result)

            try:
                api_res = await _api_capture(content.strip(), source)
            except httpx.HTTPError as e:
                result = {"content": [{"type": "text", "text": f"API error calling /capture: {e}"}], "isError": True}
                return _jsonrpc_result(request_id, result)

            text = f"Stored memory id={api_res.get('id')}"
            result = {
                "content": [{"type": "text", "text": text}],
                "structuredContent": api_res,
                "isError": False,
            }
            return _jsonrpc_result(request_id, result)

        if name == "search_memories":
            query = arguments.get("query")
            limit = arguments.get("limit", 5)
            if not isinstance(query, str) or not query.strip():
                result = {"content": [{"type": "text", "text": "query is required"}], "isError": True}
                return _jsonrpc_result(request_id, result)
            if not isinstance(limit, int):
                result = {"content": [{"type": "text", "text": "limit must be an integer"}], "isError": True}
                return _jsonrpc_result(request_id, result)

            try:
                api_res = await _api_search(query.strip(), limit)
            except httpx.HTTPError as e:
                result = {"content": [{"type": "text", "text": f"API error calling /search: {e}"}], "isError": True}
                return _jsonrpc_result(request_id, result)

            top = api_res.get("results", [])[:3]
            summary = "\n".join(
                [
                    f"score={r.get('score')}: {str(r.get('content'))[:200]}"
                    for r in top
                    if isinstance(r, dict)
                ]
            )
            if not summary:
                summary = "No results."

            result = {
                "content": [{"type": "text", "text": summary}],
                "structuredContent": api_res,
                "isError": False,
            }
            return _jsonrpc_result(request_id, result)

        if name == "get_structured_memory":
            key = arguments.get("key")
            if not isinstance(key, str) or not key.strip():
                result = {"content": [{"type": "text", "text": "key is required"}], "isError": True}
                return _jsonrpc_result(request_id, result)

            try:
                api_res = await _api_get_structured_memory(key.strip())
            except httpx.HTTPError as e:
                result = {"content": [{"type": "text", "text": f"API error calling /structured_memory: {e}"}], "isError": True}
                return _jsonrpc_result(request_id, result)

            text = json.dumps(api_res, ensure_ascii=False)
            result = {
                "content": [{"type": "text", "text": text}],
                "structuredContent": api_res,
                "isError": False,
            }
            return _jsonrpc_result(request_id, result)

        if name == "get_context":
            query = arguments.get("query")
            limit = arguments.get("limit", 5)
            key = arguments.get("key")
            if not isinstance(query, str) or not query.strip():
                result = {"content": [{"type": "text", "text": "query is required"}], "isError": True}
                return _jsonrpc_result(request_id, result)
            if not isinstance(limit, int):
                result = {"content": [{"type": "text", "text": "limit must be an integer"}], "isError": True}
                return _jsonrpc_result(request_id, result)
            if not isinstance(key, str) or not key.strip():
                result = {"content": [{"type": "text", "text": "key is required"}], "isError": True}
                return _jsonrpc_result(request_id, result)

            try:
                structured_res, search_res = await asyncio.gather(
                    _api_get_structured_memory(key.strip()),
                    _api_search(query.strip(), limit),
                )
            except httpx.HTTPError as e:
                result = {"content": [{"type": "text", "text": f"API error building context: {e}"}], "isError": True}
                return _jsonrpc_result(request_id, result)

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
            return _jsonrpc_result(request_id, result)

        result = {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}
        return _jsonrpc_result(request_id, result)

    return _jsonrpc_error(request_id, -32601, "Method not found")


def main() -> None:
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            payload = _jsonrpc_error(None, -32700, "Parse error")
            sys.stdout.write(json.dumps(payload) + "\n")
            sys.stdout.flush()
            continue

        if not isinstance(msg, dict):
            payload = _jsonrpc_error(None, -32600, "Invalid Request")
            sys.stdout.write(json.dumps(payload) + "\n")
            sys.stdout.flush()
            continue

        payload = asyncio.run(_handle_request(msg))
        if payload is None:
            continue
        sys.stdout.write(json.dumps(payload) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
