"""Live adapters: FastMCP (primary) and direct Tavily (fallback).

Errors from the network/SDK are translated into IntegrationError so the
gateway can classify retryable vs fail-fast failures.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from tavily import TavilyClient

from reliability import ContractError, IntegrationError


def _classify_exception(exc: BaseException) -> IntegrationError:
    message = str(exc) or exc.__class__.__name__
    lowered = message.lower()

    if any(token in lowered for token in ("401", "403", "forbidden", "unauthorized", "invalid api key")):
        return IntegrationError("forbidden", message, retryable=False)
    if any(token in lowered for token in ("429", "rate limit", "throttl", "quota")):
        return IntegrationError("throttled", message, retryable=True)
    if any(token in lowered for token in ("timeout", "timed out", "temporar", "unavailable", "502", "503", "504")):
        return IntegrationError("timeout", message, retryable=True)
    return IntegrationError("upstream_error", message, retryable=True)


class DirectTavilyAdapter:
    """Fallback path that calls Tavily without MCP."""

    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or os.environ.get("TAVILY_API_KEY")
        if not key:
            raise RuntimeError("TAVILY_API_KEY is required for DirectTavilyAdapter")
        self._client = TavilyClient(api_key=key)
        self.calls = 0

    def search(self, query: str) -> dict[str, Any]:
        self.calls += 1
        try:
            raw = self._client.search(query=query, max_results=5, include_answer=True)
        except Exception as exc:  # noqa: BLE001 - translate for gateway taxonomy
            raise _classify_exception(exc) from exc

        results = [
            {
                "title": item.get("title") or "",
                "url": item.get("url") or "",
                "content": item.get("content") or "",
            }
            for item in raw.get("results", [])
        ]
        answer = raw.get("answer") or (results[0]["content"] if results else "")
        if not answer:
            raise IntegrationError("empty_result", "tavily returned no answer", retryable=False)
        return {
            "query": query,
            "answer": answer,
            "results": results,
            "provider": "tavily-direct",
        }


class FastMcpSearchAdapter:
    """Primary path: call web_search on the local FastMCP server over stdio."""

    def __init__(self, server_script: Path | None = None) -> None:
        self.server_script = Path(server_script or Path(__file__).with_name("mcp_server.py")).resolve()
        self.calls = 0

    def search(self, query: str) -> dict[str, Any]:
        self.calls += 1
        try:
            return asyncio.run(self._asearch(query))
        except IntegrationError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise _classify_exception(exc) from exc

    async def _asearch(self, query: str) -> dict[str, Any]:
        from langchain_mcp_adapters.client import MultiServerMCPClient

        env = {**os.environ}
        client = MultiServerMCPClient(
            {
                "search": {
                    "transport": "stdio",
                    "command": os.environ.get("PYTHON", "python"),
                    "args": [str(self.server_script)],
                    "env": env,
                }
            }
        )
        tools = await client.get_tools()
        tool = next((item for item in tools if item.name == "web_search"), None)
        if tool is None:
            raise IntegrationError("tool_missing", "web_search tool not found on FastMCP server", retryable=False)

        try:
            raw = await tool.ainvoke({"query": query, "max_results": 5})
        except Exception as exc:  # noqa: BLE001
            raise _classify_exception(exc) from exc

        return _normalize_tool_payload(raw, query=query)


def _normalize_tool_payload(raw: Any, *, query: str) -> dict[str, Any]:
    """LangChain MCP tools may return dict or JSON text; normalize to gateway contract."""
    import json

    payload = raw
    if isinstance(raw, str):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ContractError(f"non-json MCP payload: {raw[:120]}") from exc

    if not isinstance(payload, dict):
        raise ContractError("MCP tool did not return an object")

    if "query" not in payload:
        payload = {**payload, "query": query}
    if "answer" not in payload or not payload["answer"]:
        results = payload.get("results") or []
        if results and isinstance(results[0], dict):
            payload = {**payload, "answer": results[0].get("content") or ""}
    return payload
