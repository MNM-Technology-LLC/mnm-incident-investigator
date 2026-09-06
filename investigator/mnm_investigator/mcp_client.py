"""A bounded client for the dedicated, read-only telemetry MCP service."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import hashlib
import hmac
import json
import os
import re
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from .models import TOOL_ARGUMENTS
from .telemetry import canonical_json, parse_utc, utc_string

ALLOWED_TOOLS = frozenset({
    "get_service_health", "get_service_map", "query_metrics", "search_logs", "get_trace",
})
MAX_TOOL_BYTES = 65_536


class ToolPermissionError(ValueError):
    pass


def _mcp_http_client(headers=None, timeout=None, auth=None):
    # SDK defaults enable redirects and environment proxies; neither is permitted here.
    return httpx.AsyncClient(headers=headers, timeout=timeout, auth=auth,
                             follow_redirects=False, trust_env=False)


def _only_transport_errors(error: ExceptionGroup) -> bool:
    return all(_only_transport_errors(item) if isinstance(item, ExceptionGroup)
               else isinstance(item, (ConnectionError, httpx.HTTPError, OSError, TimeoutError))
               for item in error.exceptions)


def validate_evidence(value: Any, *, name: str | None = None, arguments: dict | None = None,
                      evidence_id: str | None = None) -> dict:
    """Check content integrity and query provenance, never treating IDs as signatures."""
    if not isinstance(value, dict) or len(canonical_json(value).encode()) > MAX_TOOL_BYTES:
        raise ValueError("Invalid or oversized telemetry result")
    if (set(value) != {"evidence_id", "tool", "query", "data", "available", "limitations"}
            or not isinstance(value["tool"], str) or value["tool"] not in ALLOWED_TOOLS
            or not isinstance(value["data"], dict) or type(value["available"]) is not bool
            or not isinstance(value["limitations"], list)
            or any(not isinstance(note, str) for note in value["limitations"])):
        raise ValueError("Telemetry result has an invalid evidence schema")
    observed_id = value["evidence_id"]
    if not isinstance(observed_id, str) or not re.fullmatch(r"ev_[a-f0-9]{64}", observed_id):
        raise ValueError("Telemetry result has no verifiable provenance")
    content = {key: item for key, item in value.items() if key != "evidence_id"}
    expected_id = "ev_" + hashlib.sha256(canonical_json(content).encode()).hexdigest()
    if not hmac.compare_digest(observed_id, expected_id) or evidence_id is not None and observed_id != evidence_id:
        raise ValueError("Telemetry evidence checksum or requested ID does not match")
    if name is not None and value["tool"] != name:
        raise ValueError("Telemetry result came from a different tool")

    def normalized(query):
        result = TOOL_ARGUMENTS[value["tool"]].model_validate(query).model_dump(exclude_none=True)
        for key in ("start", "end"):
            result[key] = utc_string(parse_utc(result[key]))
        return result

    query = normalized(value["query"])
    if arguments is not None and query != normalized(arguments):
        raise ValueError("Telemetry result does not match the requested filters and window")
    return value


class MCPSession:
    def __init__(self, session: ClientSession):
        self._session = session

    async def list_tools(self) -> list[dict[str, Any]]:
        async with asyncio.timeout(8):
            response = await self._session.list_tools()
        # Unknown MCP capabilities never become model permissions.
        return [
            {"type": "function", "function": {
                "name": t.name,
                "description": t.description or "Read bounded application telemetry.",
                "parameters": t.inputSchema,
            }}
            for t in response.tools if t.name in ALLOWED_TOOLS
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(name, str) or name not in ALLOWED_TOOLS:
            raise ToolPermissionError("Only the five read-only telemetry tools are permitted")
        if not isinstance(arguments, dict) or len(json.dumps(arguments)) > 4000:
            raise ValueError("Invalid or oversized tool arguments")
        arguments = TOOL_ARGUMENTS[name].model_validate(arguments).model_dump(exclude_none=True)
        async with asyncio.timeout(8):
            response = await self._session.call_tool(name, arguments)
        if response.isError:
            raise ValueError("Telemetry rejected the tool arguments or query")
        value = response.structuredContent
        if value is None:
            contents = [c.text for c in response.content if c.type == "text"]
            raw = "".join(contents)
            if len(raw.encode()) > MAX_TOOL_BYTES:
                raise ValueError("Telemetry result exceeds the response budget")
            value = json.loads(raw)
        return validate_evidence(value, name=name, arguments=arguments)


class MCPGateway:
    def __init__(self, url: str | None = None):
        self.url = url or os.getenv("MCP_URL", "http://127.0.0.1:8001/mcp")

    @asynccontextmanager
    async def session(self):
        # Session creation and each operation have independent deadlines.
        try:
            async with streamablehttp_client(self.url, timeout=8, sse_read_timeout=10,
                                             httpx_client_factory=_mcp_http_client) as (read, write, _):
                async with ClientSession(read, write) as session:
                    async with asyncio.timeout(8):
                        await session.initialize()
                    yield MCPSession(session)
        except ExceptionGroup as error:
            # AnyIO wraps SDK transport failures. Keep model/schema errors and cancellation intact.
            if not _only_transport_errors(error):
                raise
            raise ConnectionError("Read-only telemetry connection is unavailable") from error

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        async with self.session() as session:
            return await session.call_tool(name, arguments)

    async def evidence(self, evidence_id: str) -> dict[str, Any] | None:
        if not re.fullmatch(r"ev_[a-f0-9]{64}", evidence_id):
            return None
        base = self.url.rsplit("/mcp", 1)[0]
        async with httpx.AsyncClient(timeout=8, follow_redirects=False, trust_env=False) as client:
            async with client.stream("GET", f"{base}/evidence/{evidence_id}") as response:
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > MAX_TOOL_BYTES:
                        raise ValueError("Evidence exceeds response budget")
                    body.extend(chunk)
            return validate_evidence(json.loads(body), evidence_id=evidence_id)
