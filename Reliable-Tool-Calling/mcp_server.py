"""FastMCP server that exposes real Tavily web search.

Run standalone:
    python mcp_server.py

Or let the LangGraph agent spawn it over stdio via MultiServerMCPClient.
"""

from __future__ import annotations

import os
from typing import Any

from fastmcp import FastMCP
from tavily import TavilyClient

mcp = FastMCP("reliable-search")


def _tavily() -> TavilyClient:
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY is required for the FastMCP search server")
    return TavilyClient(api_key=api_key)


@mcp.tool
def web_search(query: str, max_results: int = 5) -> dict[str, Any]:
    """Search the live web with Tavily and return a structured payload.

    Returns a contract the reliability gateway can validate:
    query, answer, results[{title, url, content}], and provider.
    """
    if not query or not query.strip():
        raise ValueError("query must be a non-empty string")

    client = _tavily()
    raw = client.search(
        query=query.strip(),
        max_results=max(1, min(max_results, 10)),
        include_answer=True,
    )

    results = [
        {
            "title": item.get("title") or "",
            "url": item.get("url") or "",
            "content": item.get("content") or "",
        }
        for item in raw.get("results", [])
    ]
    answer = raw.get("answer") or (results[0]["content"] if results else "")

    return {
        "query": query.strip(),
        "answer": answer,
        "results": results,
        "provider": "tavily",
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
