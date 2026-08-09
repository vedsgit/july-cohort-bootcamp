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


def retry_call(operation, policy, *, trace, sleep=time.sleep):
    # TODO 2: bounded attempts, error classification, backoff, and trace events.
    raise NotImplementedError


class CircuitBreaker:
    CLOSED, OPEN, HALF_OPEN = "closed", "open", "half_open"

    def __init__(self, failure_threshold=3, recovery_timeout=5.0, *, clock=time.monotonic, trace=None):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.clock = clock
        self.trace = trace or Trace()
        self.state = self.CLOSED
        self.consecutive_failures = 0
        self.opened_at = None

    def before_call(self):
        # TODO 3: reject OPEN or transition to HALF_OPEN after timeout.
        raise NotImplementedError

    def record_success(self):
        # TODO 4: reset and close.
        raise NotImplementedError

    def record_failure(self):
        # TODO 5: count failures and open/reopen when required.
        raise NotImplementedError

    def execute(self, operation):
        self.before_call()
        try:
            result = operation()
        except IntegrationError:
            self.record_failure()
            raise
        self.record_success()
        return result


class FixedWindowRateLimiter:
    def __init__(self, limit=5, window_seconds=60.0, *, clock=time.monotonic, trace=None):
        self.limit, self.window_seconds, self.clock = limit, window_seconds, clock
        self.trace = trace or Trace()
        self._windows = {}

    def check(self, key):
        # TODO 6: enforce a per-key fixed window and emit trace events.
        raise NotImplementedError


@dataclass(frozen=True)
class SearchResult:
    query: str
    answer: str
    source: str
    degraded: bool
    citations: tuple[str, ...] = ()


class SearchAdapter(Protocol):
    def search(self, query: str) -> Any: ...


def validate_search_result(payload, *, source, degraded):
    # TODO 7: validate required fields and return SearchResult.
    raise NotImplementedError


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
    def __init__(self, mcp_adapter, direct_adapter, *, retry_policy, breaker, limiter, trace, sleep=time.sleep):
        self.mcp_adapter, self.direct_adapter = mcp_adapter, direct_adapter
        self.retry_policy, self.breaker, self.limiter = retry_policy, breaker, limiter
        self.trace, self.sleep, self._cache = trace, sleep, {}

    def search(self, query, *, tenant, request_id):
        # TODO 8: rate limit, idempotency, retry + breaker, safe fallback, validation.
        raise NotImplementedError
