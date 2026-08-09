"""Learner starter: implement the TODOs without changing the public interfaces."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Protocol
import time


class IntegrationError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class CircuitOpenError(IntegrationError):
    def __init__(self) -> None:
        super().__init__("circuit_open", "dependency circuit is open", retryable=True)


class RateLimitError(IntegrationError):
    def __init__(self) -> None:
        super().__init__("rate_limited", "tenant request limit exceeded", retryable=False)


class ContractError(IntegrationError):
    def __init__(self, message: str) -> None:
        super().__init__("invalid_contract", message, retryable=False)


@dataclass(frozen=True)
class TraceEvent:
    name: str
    attributes: dict[str, Any]


@dataclass
class Trace:
    events: list[TraceEvent] = field(default_factory=list)

    def emit(self, name: str, **attributes: Any) -> None:
        self.events.append(TraceEvent(name, attributes))

    def names(self) -> list[str]:
        return [event.name for event in self.events]


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 0.2
    max_delay: float = 2.0
    jitter_ratio: float = 0.0

    def delay_for_attempt(self, failed_attempt: int, random_value: Callable[[], float] = lambda: 0.5) -> float:
        if failed_attempt < 1:
            raise ValueError("failed_attempt must be greater than 0")
        raw = min(self.max_delay, self.base_delay * (2 ** (failed_attempt - 1)))
        spread = raw * self.jitter_ratio
        return max(0, raw - spread + (2*spread*random_value()))


def retry_call(
    operation: Callable[[], Any],
    policy: RetryPolicy,
    *,
    trace: Trace,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    if policy.max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    for attempt in range(1, policy.max_attempts + 1):
        trace.emit("retry.attempt", attempt=attempt)
        try:
            result = operation()
            trace.emit("retry.success", attempt=attempt)
            return result
        except IntegrationError as error:
            trace.emit(
                "retry.failure",
                attempt=attempt,
                code=error.code,
                retryable=error.retryable,
            )
            if not error.retryable or attempt == policy.max_attempts:
                raise
            delay = policy.delay_for_attempt(attempt)
            trace.emit("retry.backoff", attempt=attempt, seconds=delay)
            sleep(delay)

    raise AssertionError("retry loop terminated unexpectedly")



class CircuitBreaker:
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout: float = 5.0,
        *,
        clock: Callable[[], float] = time.monotonic,
        trace: Trace | None = None,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.clock = clock
        self.trace = trace or Trace()
        self.state = self.CLOSED
        self.consecutive_failures = 0
        self.opened_at: float | None = None

    def _transition(self, state: str) -> None:
        previous = self.state
        self.state = state
        self.trace.emit("circuit.transition", previous=previous, current=state)

    def before_call(self) -> None:
        if self.state == self.OPEN:
            assert self.opened_at is not None
            if self.clock() - self.opened_at >= self.recovery_timeout:
                self._transition(self.HALF_OPEN)
            else:
                self.trace.emit("circuit.rejected", state=self.state)
                raise CircuitOpenError()

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.opened_at = None
        if self.state != self.CLOSED:
            self._transition(self.CLOSED)

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        if self.state == self.HALF_OPEN or self.consecutive_failures >= self.failure_threshold:
            self.opened_at = self.clock()
            if self.state != self.OPEN:
                self._transition(self.OPEN)

    def execute(self, operation: Callable[[], Any]) -> Any:
        self.before_call()
        try:
            result = operation()
        except IntegrationError:
            self.record_failure()
            raise
        self.record_success()
        return result


class FixedWindowRateLimiter:
    def __init__(
        self,
        limit: int = 5,
        window_seconds: float = 60.0,
        *,
        clock: Callable[[], float] = time.monotonic,
        trace: Trace | None = None,
    ) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.clock = clock
        self.trace = trace or Trace()
        self._windows: dict[str, tuple[float, int]] = {}

    def check(self, key: str) -> None:
        now = self.clock()
        started_at, count = self._windows.get(key, (now, 0))
        if now - started_at >= self.window_seconds:
            started_at, count = now, 0
        if count >= self.limit:
            self.trace.emit("rate_limit.rejected", key=key, limit=self.limit)
            raise RateLimitError()
        self._windows[key] = (started_at, count + 1)
        self.trace.emit("rate_limit.allowed", key=key, remaining=self.limit - count - 1)



@dataclass(frozen=True)
class SearchResult:
    query: str
    answer: str
    source: str
    degraded: bool
    citations: tuple[str, ...] = ()


class SearchAdapter(Protocol):
    def search(self, query: str) -> Any: ...


def validate_search_result(payload: Any, *, source: str, degraded: bool) -> SearchResult:
    if not isinstance(payload, dict):
        raise ContractError("response must be an object")
    query = payload.get("query")
    answer = payload.get("answer")
    if not isinstance(query, str) or not query.strip():
        raise ContractError("query must be a non-empty string")
    if not isinstance(answer, str) or not answer.strip():
        raise ContractError("answer must be a non-empty string")

    citations: list[str] = []
    results = payload.get("results")
    if isinstance(results, list):
        for item in results:
            if isinstance(item, dict) and isinstance(item.get("url"), str) and item["url"]:
                citations.append(item["url"])

    return SearchResult(
        query=query.strip(),
        answer=answer.strip(),
        source=source,
        degraded=degraded,
        citations=tuple(citations),
    )



class ScriptedAdapter:
    def __init__(self, outcomes: Iterable[Any], name: str):
        self.outcomes, self.name, self.calls = list(outcomes), name, 0

    def search(self, query):
        self.calls += 1
        if not self.outcomes:
            raise IntegrationError("script_exhausted", f"{self.name} has no outcome", retryable=False)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, dict) and "query" not in outcome:
            return {**outcome, "query": query}
        return outcome


class ReliableSearchGateway:
    def __init__(
        self,
        mcp_adapter: SearchAdapter,
        direct_adapter: SearchAdapter,
        *,
        retry_policy: RetryPolicy,
        breaker: CircuitBreaker,
        limiter: FixedWindowRateLimiter,
        trace: Trace,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.mcp_adapter = mcp_adapter
        self.direct_adapter = direct_adapter
        self.retry_policy = retry_policy
        self.breaker = breaker
        self.limiter = limiter
        self.trace = trace
        self.sleep = sleep
        self._cache: dict[tuple[str, str], SearchResult] = {}

    def search(self, query: str, *, tenant: str, request_id: str) -> SearchResult:
        self.limiter.check(tenant)
        cache_key = (tenant, request_id)
        if cache_key in self._cache:
            self.trace.emit("idempotency.hit", tenant=tenant, request_id=request_id)
            return self._cache[cache_key]

        def call_mcp() -> Any:
            return retry_call(
                lambda: self.mcp_adapter.search(query),
                self.retry_policy,
                trace=self.trace,
                sleep=self.sleep,
            )

        try:
            payload = self.breaker.execute(call_mcp)
            result = validate_search_result(payload, source="mcp", degraded=False)
        except IntegrationError as error:
            if not error.retryable:
                self.trace.emit("gateway.fail_fast", code=error.code)
                raise
            self.trace.emit("fallback.started", reason=error.code)
            fallback_payload = self.direct_adapter.search(query)
            result = validate_search_result(fallback_payload, source="direct", degraded=True)
            self.trace.emit("fallback.succeeded", source="direct")

        self._cache[cache_key] = result
        return result
