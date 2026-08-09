import unittest

from reliability import (
    CircuitBreaker,
    CircuitOpenError,
    ContractError,
    FakeClock,
    FixedWindowRateLimiter,
    IntegrationError,
    RateLimitError,
    ReliableSearchGateway,
    RetryPolicy,
    ScriptedAdapter,
    Trace,
    retry_call,
    validate_search_result,
)


def transient(code="timeout"):
    return IntegrationError(code, code, retryable=True)


def forbidden():
    return IntegrationError("forbidden", "forbidden", retryable=False)


def ok_payload(query="q", answer="a", url="https://example.com"):
    return {
        "query": query,
        "answer": answer,
        "results": [{"title": "Example", "url": url, "content": answer}],
    }


class RetryTests(unittest.TestCase):
    def test_01_transient_failure_then_success(self):
        trace, sleeps = Trace(), []
        adapter = ScriptedAdapter([transient(), ok_payload()], "mcp")
        result = retry_call(lambda: adapter.search("q"), RetryPolicy(), trace=trace, sleep=sleeps.append)
        self.assertEqual("a", result["answer"])
        self.assertEqual(2, adapter.calls)

    def test_02_non_retryable_fails_fast(self):
        adapter = ScriptedAdapter([forbidden(), ok_payload()], "mcp")
        with self.assertRaises(IntegrationError):
            retry_call(lambda: adapter.search("q"), RetryPolicy(), trace=Trace(), sleep=lambda _: None)
        self.assertEqual(1, adapter.calls)

    def test_03_max_attempts_is_enforced(self):
        adapter = ScriptedAdapter([transient(), transient(), transient()], "mcp")
        with self.assertRaises(IntegrationError):
            retry_call(lambda: adapter.search("q"), RetryPolicy(max_attempts=2), trace=Trace(), sleep=lambda _: None)
        self.assertEqual(2, adapter.calls)

    def test_04_exponential_backoff_is_capped(self):
        policy = RetryPolicy(base_delay=0.25, max_delay=0.5)
        self.assertEqual([0.25, 0.5, 0.5], [policy.delay_for_attempt(n) for n in (1, 2, 3)])

    def test_05_trace_records_retry_lifecycle(self):
        trace = Trace()
        adapter = ScriptedAdapter([transient(), ok_payload()], "mcp")
        retry_call(lambda: adapter.search("q"), RetryPolicy(), trace=trace, sleep=lambda _: None)
        self.assertEqual(
            ["retry.attempt", "retry.failure", "retry.backoff", "retry.attempt", "retry.success"],
            trace.names(),
        )


class CircuitBreakerTests(unittest.TestCase):
    def test_06_opens_after_threshold(self):
        clock, trace = FakeClock(), Trace()
        breaker = CircuitBreaker(failure_threshold=2, clock=clock, trace=trace)
        for _ in range(2):
            with self.assertRaises(IntegrationError):
                breaker.execute(lambda: (_ for _ in ()).throw(transient()))
        self.assertEqual(CircuitBreaker.OPEN, breaker.state)

    def test_07_open_circuit_rejects_without_calling_dependency(self):
        clock = FakeClock()
        breaker = CircuitBreaker(failure_threshold=1, clock=clock)
        with self.assertRaises(IntegrationError):
            breaker.execute(lambda: (_ for _ in ()).throw(transient()))
        calls = []
        with self.assertRaises(CircuitOpenError):
            breaker.execute(lambda: calls.append(True))
        self.assertEqual([], calls)

    def test_08_successful_half_open_probe_closes(self):
        clock = FakeClock()
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=5, clock=clock)
        with self.assertRaises(IntegrationError):
            breaker.execute(lambda: (_ for _ in ()).throw(transient()))
        clock.advance(5)
        self.assertEqual("ok", breaker.execute(lambda: "ok"))
        self.assertEqual(CircuitBreaker.CLOSED, breaker.state)

    def test_09_failed_half_open_probe_reopens(self):
        clock = FakeClock()
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=5, clock=clock)
        with self.assertRaises(IntegrationError):
            breaker.execute(lambda: (_ for _ in ()).throw(transient()))
        clock.advance(5)
        with self.assertRaises(IntegrationError):
            breaker.execute(lambda: (_ for _ in ()).throw(transient()))
        self.assertEqual(CircuitBreaker.OPEN, breaker.state)
        self.assertEqual(5, breaker.opened_at)


class RateLimiterTests(unittest.TestCase):
    def test_10_limit_is_enforced_per_key(self):
        limiter = FixedWindowRateLimiter(limit=1, clock=FakeClock())
        limiter.check("acme")
        with self.assertRaises(RateLimitError):
            limiter.check("acme")
        limiter.check("globex")

    def test_11_window_resets(self):
        clock = FakeClock()
        limiter = FixedWindowRateLimiter(limit=1, window_seconds=10, clock=clock)
        limiter.check("acme")
        clock.advance(10)
        limiter.check("acme")


class ContractTests(unittest.TestCase):
    def test_12_valid_contract_is_normalized(self):
        result = validate_search_result(ok_payload("q1", "shipped"), source="mcp", degraded=False)
        self.assertEqual("q1", result.query)
        self.assertEqual("shipped", result.answer)
        self.assertEqual("mcp", result.source)
        self.assertFalse(result.degraded)
        self.assertEqual(("https://example.com",), result.citations)

    def test_13_missing_answer_is_rejected(self):
        with self.assertRaises(ContractError):
            validate_search_result({"query": "q"}, source="mcp", degraded=False)

    def test_14_empty_query_is_rejected(self):
        with self.assertRaises(ContractError):
            validate_search_result({"query": " ", "answer": "x"}, source="mcp", degraded=False)


class GatewayTests(unittest.TestCase):
    def make_gateway(self, mcp_outcomes, direct_outcomes, *, attempts=2, limit=10):
        clock, trace = FakeClock(), Trace()
        mcp = ScriptedAdapter(mcp_outcomes, "mcp")
        direct = ScriptedAdapter(direct_outcomes, "direct")
        gateway = ReliableSearchGateway(
            mcp,
            direct,
            retry_policy=RetryPolicy(max_attempts=attempts),
            breaker=CircuitBreaker(failure_threshold=2, clock=clock, trace=trace),
            limiter=FixedWindowRateLimiter(limit=limit, clock=clock, trace=trace),
            trace=trace,
            sleep=clock.advance,
        )
        return gateway, mcp, direct, trace

    def test_15_happy_path_uses_mcp(self):
        gateway, _, direct, _ = self.make_gateway([ok_payload()], [])
        result = gateway.search("q", tenant="acme", request_id="r1")
        self.assertEqual(("mcp", False, 0), (result.source, result.degraded, direct.calls))

    def test_16_retry_exhaustion_uses_degraded_fallback(self):
        gateway, mcp, direct, trace = self.make_gateway(
            [transient(), transient()], [ok_payload(answer="fallback")]
        )
        result = gateway.search("q", tenant="acme", request_id="r1")
        self.assertEqual(("direct", True, 2, 1), (result.source, result.degraded, mcp.calls, direct.calls))
        self.assertIn("fallback.succeeded", trace.names())

    def test_17_forbidden_does_not_fallback(self):
        gateway, _, direct, trace = self.make_gateway([forbidden()], [ok_payload()])
        with self.assertRaises(IntegrationError):
            gateway.search("q", tenant="acme", request_id="r1")
        self.assertEqual(0, direct.calls)
        self.assertIn("gateway.fail_fast", trace.names())

    def test_18_idempotency_key_reuses_result(self):
        gateway, mcp, _, trace = self.make_gateway([ok_payload()], [])
        first = gateway.search("q", tenant="acme", request_id="same")
        second = gateway.search("q", tenant="acme", request_id="same")
        self.assertIs(first, second)
        self.assertEqual(1, mcp.calls)
        self.assertIn("idempotency.hit", trace.names())

    def test_19_local_rate_limit_does_not_fallback(self):
        gateway, _, direct, _ = self.make_gateway([ok_payload()], [], limit=0)
        with self.assertRaises(RateLimitError):
            gateway.search("q", tenant="acme", request_id="r1")
        self.assertEqual(0, direct.calls)


if __name__ == "__main__":
    unittest.main()
