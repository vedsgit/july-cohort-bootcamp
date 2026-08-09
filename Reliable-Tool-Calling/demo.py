"""Classroom demos for every reliability path used in the Sunday script.

The scripted scenarios are deterministic and require no API keys. The optional
live path uses LangGraph + OpenAI + FastMCP/Tavily when credentials are present.
"""

from __future__ import annotations

import asyncio
import os
import sys

from reliability import (
    CircuitBreaker,
    FakeClock,
    FixedWindowRateLimiter,
    IntegrationError,
    ReliableSearchGateway,
    RetryPolicy,
    ScriptedAdapter,
    Trace,
)


def transient(code: str) -> IntegrationError:
    return IntegrationError(code, f"simulated {code}", retryable=True)


def payload(answer: str, *, query: str = "FastMCP reliability") -> dict[str, object]:
    return {
        "query": query,
        "answer": answer,
        "results": [{"title": "FastMCP", "url": "https://gofastmcp.com", "content": answer}],
    }


def build_scripted_gateway(
    mcp_outcomes: list[object],
    direct_outcomes: list[object],
    *,
    attempts: int = 3,
    failure_threshold: int = 3,
    limit: int = 5,
) -> tuple[ReliableSearchGateway, ScriptedAdapter, ScriptedAdapter, Trace, FakeClock]:
    clock = FakeClock()
    trace = Trace()
    mcp = ScriptedAdapter(mcp_outcomes, "mcp")
    direct = ScriptedAdapter(direct_outcomes, "direct")
    gateway = ReliableSearchGateway(
        mcp,
        direct,
        retry_policy=RetryPolicy(max_attempts=attempts, base_delay=0.2),
        breaker=CircuitBreaker(
            failure_threshold=failure_threshold,
            clock=clock,
            trace=trace,
        ),
        limiter=FixedWindowRateLimiter(limit=limit, clock=clock, trace=trace),
        trace=trace,
        sleep=clock.advance,
    )
    return gateway, mcp, direct, trace, clock


def show(name: str, *, trace: Trace, calls: str, result: object | None = None) -> None:
    print(f"\n=== {name} ===")
    if result is not None:
        print(result)
    print(calls)
    for event in trace.events:
        print(f"{event.name:24} {event.attributes}")


def scenario_retry() -> None:
    gateway, mcp, direct, trace, _ = build_scripted_gateway(
        [
            transient("timeout"),
            transient("throttled"),
            payload("The MCP path recovered on attempt three."),
        ],
        [payload("The direct fallback answered.")],
    )
    result = gateway.search("FastMCP reliability", tenant="acme", request_id="retry-1")
    show(
        "retry then primary success",
        result=result,
        calls=f"mcp_calls={mcp.calls} direct_calls={direct.calls}",
        trace=trace,
    )


def scenario_fallback() -> None:
    gateway, mcp, direct, trace, _ = build_scripted_gateway(
        [transient("timeout"), transient("timeout")],
        [payload("The approved direct path answered in degraded mode.")],
        attempts=2,
    )
    result = gateway.search("FastMCP reliability", tenant="acme", request_id="fallback-1")
    show(
        "retry exhaustion then fallback",
        result=result,
        calls=f"mcp_calls={mcp.calls} direct_calls={direct.calls}",
        trace=trace,
    )


def scenario_forbidden() -> None:
    forbidden = IntegrationError("forbidden", "simulated forbidden", retryable=False)
    gateway, mcp, direct, trace, _ = build_scripted_gateway(
        [forbidden],
        [payload("This fallback must not run.")],
    )
    try:
        gateway.search("FastMCP reliability", tenant="acme", request_id="forbidden-1")
    except IntegrationError as error:
        result = f"error={error.code} retryable={error.retryable}"
    else:  # pragma: no cover - classroom guardrail
        result = "unexpected success"
    show(
        "forbidden fails fast",
        result=result,
        calls=f"mcp_calls={mcp.calls} direct_calls={direct.calls}",
        trace=trace,
    )


def scenario_contract() -> None:
    gateway, mcp, direct, trace, _ = build_scripted_gateway(
        [{"query": "FastMCP reliability", "results": []}],
        [payload("This fallback must not hide contract drift.")],
    )
    try:
        gateway.search("FastMCP reliability", tenant="acme", request_id="contract-1")
    except IntegrationError as error:
        result = f"error={error.code} retryable={error.retryable}"
    else:  # pragma: no cover - classroom guardrail
        result = "unexpected success"
    show(
        "invalid contract fails fast",
        result=result,
        calls=f"mcp_calls={mcp.calls} direct_calls={direct.calls}",
        trace=trace,
    )


def scenario_breaker() -> None:
    gateway, mcp, direct, trace, _ = build_scripted_gateway(
        [transient("timeout")],
        [
            payload("Fallback served the first request."),
            payload("Fallback served the open-circuit request."),
        ],
        attempts=1,
        failure_threshold=1,
    )
    first = gateway.search("FastMCP reliability", tenant="acme", request_id="breaker-1")
    second = gateway.search("FastMCP reliability", tenant="acme", request_id="breaker-2")
    show(
        "open circuit skips the MCP dependency",
        result=f"first={first.source}/{first.degraded} second={second.source}/{second.degraded}",
        calls=f"mcp_calls={mcp.calls} direct_calls={direct.calls}",
        trace=trace,
    )


def scenario_rate_limit() -> None:
    gateway, mcp, direct, trace, _ = build_scripted_gateway(
        [payload("The admitted request succeeded.")],
        [],
        limit=1,
    )
    gateway.search("FastMCP reliability", tenant="acme", request_id="limit-1")
    try:
        gateway.search("FastMCP reliability", tenant="acme", request_id="limit-2")
    except IntegrationError as error:
        result = f"error={error.code} retryable={error.retryable}"
    else:  # pragma: no cover - classroom guardrail
        result = "unexpected success"
    show(
        "local rate limit rejects without fallback",
        result=result,
        calls=f"mcp_calls={mcp.calls} direct_calls={direct.calls}",
        trace=trace,
    )


def scenario_idempotency() -> None:
    gateway, mcp, direct, trace, _ = build_scripted_gateway(
        [payload("The original result is reused.")],
        [],
    )
    first = gateway.search("FastMCP reliability", tenant="acme", request_id="same")
    second = gateway.search("FastMCP reliability", tenant="acme", request_id="same")
    show(
        "idempotent replay reuses the cached result",
        result=f"same_object={first is second}",
        calls=f"mcp_calls={mcp.calls} direct_calls={direct.calls}",
        trace=trace,
    )


SCENARIOS = {
    "retry": scenario_retry,
    "fallback": scenario_fallback,
    "forbidden": scenario_forbidden,
    "contract": scenario_contract,
    "breaker": scenario_breaker,
    "rate-limit": scenario_rate_limit,
    "idempotency": scenario_idempotency,
}


def run_scripted_demo(scenario: str = "retry") -> None:
    if scenario == "all":
        for run in SCENARIOS.values():
            run()
        return
    try:
        SCENARIOS[scenario]()
    except KeyError as exc:
        choices = ", ".join([*SCENARIOS, "all"])
        raise SystemExit(f"Unknown scenario {scenario!r}. Choose: {choices}") from exc


async def run_live_demo(question: str) -> None:
    from agent import arun_agent

    payload = await arun_agent(question)
    messages = payload["result"]["messages"]
    print(messages[-1].content)
    print("--- reliability trace ---")
    for event in payload["trace"].events:
        print(f"{event.name:24} {event.attributes}")


def main() -> None:
    if "--live" in sys.argv:
        missing = [key for key in ("OPENAI_API_KEY", "TAVILY_API_KEY") if not os.environ.get(key)]
        if missing:
            raise SystemExit(f"Missing env vars for live demo: {', '.join(missing)}")
        question = " ".join(arg for arg in sys.argv[1:] if arg != "--live").strip()
        question = question or "What is FastMCP and why prefer it over mcp.server.fastmcp?"
        asyncio.run(run_live_demo(question))
        return

    scenario = "retry"
    if "--scenario" in sys.argv:
        index = sys.argv.index("--scenario")
        try:
            scenario = sys.argv[index + 1]
        except IndexError as exc:
            raise SystemExit("--scenario requires a value") from exc
    run_scripted_demo(scenario)


if __name__ == "__main__":
    main()
