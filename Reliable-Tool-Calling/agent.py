"""LangGraph research agent that reaches Tavily only through the reliability gateway.

Uses LangChain ChatOpenAI + create_agent — not the OpenAI SDK.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from adapters import DirectTavilyAdapter, FastMcpSearchAdapter
from reliability import (
    CircuitBreaker,
    FixedWindowRateLimiter,
    ReliableSearchGateway,
    RetryPolicy,
    Trace,
)

load_dotenv()



class WebSearchInput(BaseModel):
    query: str = Field(description="Natural-language web search query")


def build_gateway(*, trace: Trace | None = None) -> tuple[ReliableSearchGateway, Trace]:
    events = trace or Trace()
    gateway = ReliableSearchGateway(
        FastMcpSearchAdapter(),
        DirectTavilyAdapter(),
        retry_policy=RetryPolicy(max_attempts=3, base_delay=0.4, max_delay=2.0),
        breaker=CircuitBreaker(failure_threshold=3, recovery_timeout=8.0, trace=events),
        limiter=FixedWindowRateLimiter(limit=20, window_seconds=60.0, trace=events),
        trace=events,
    )
    return gateway, events


def gateway_search_tool(gateway: ReliableSearchGateway, *, tenant: str) -> StructuredTool:
    def _search(query: str) -> str:
        result = gateway.search(query, tenant=tenant, request_id=str(uuid.uuid4()))
        cites = "\n".join(f"- {url}" for url in result.citations[:5])
        degraded = "yes" if result.degraded else "no"
        return (
            f"answer: {result.answer}\n"
            f"source: {result.source}\n"
            f"degraded: {degraded}\n"
            f"citations:\n{cites or '- none'}"
        )

    return StructuredTool.from_function(
        func=_search,
        name="reliable_web_search",
        description=(
            "Search the live web through the reliability gateway "
            "(FastMCP/Tavily primary, direct Tavily fallback)."
        ),
        args_schema=WebSearchInput,
    )


def build_agent(*, tenant: str = "acme", model: str | None = None) -> tuple[Any, Trace]:
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required for the LangGraph agent")
    if not os.environ.get("TAVILY_API_KEY"):
        raise RuntimeError("TAVILY_API_KEY is required for Tavily search")

    gateway, trace = build_gateway()
    llm = ChatOpenAI(model=model or os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"), temperature=0)
    tool = gateway_search_tool(gateway, tenant=tenant)
    agent = create_agent(llm, tools=[tool])
    return agent, trace


async def arun_agent(question: str, *, tenant: str = "acme") -> dict[str, Any]:
    agent, trace = build_agent(tenant=tenant)
    result = await agent.ainvoke({"messages": [{"role": "user", "content": question}]})
    return {"result": result, "trace": trace}
