from decimal import Decimal
from pathlib import Path
from typing import Any

from .audit import AuditSink, build_audit_sink, default_audit_log_path
from .contracts import (
    Operation,
    OrderStatusInput,
    OrderStatusOutput,
    RefundInput,
    RefundOutput,
    RiskTier,
)
from .gateway import ToolGateway
from .policy import PolicyEngine
from .registry import ToolDefinition, ToolRegistry
from .tools import SupportToolBackend, default_idempotency_store_path

_UNSET: Any = object()


def build_gateway(
    *,
    audit_log_path: str | Path | None = _UNSET,
    idempotency_store_path: str | Path | None = _UNSET,
) -> tuple[ToolGateway, SupportToolBackend, AuditSink]:
    """
    Build the tool gateway.

    audit_log_path / idempotency_store_path:
      - omitted → durable files under logs/ (demo / prod-shaped defaults)
      - Path/str → that file
      - None → ephemeral in-memory only (unit tests)
    """
    if audit_log_path is _UNSET:
        resolved_audit: str | Path | None = default_audit_log_path()
    else:
        resolved_audit = audit_log_path

    if idempotency_store_path is _UNSET:
        # Keep tests isolated when audit is in-memory.
        if resolved_audit is None:
            resolved_idem: str | Path | None = None
        else:
            resolved_idem = default_idempotency_store_path()
    else:
        resolved_idem = idempotency_store_path

    backend = SupportToolBackend(idempotency_store_path=resolved_idem)
    audit = build_audit_sink(resolved_audit)
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="get_order_status",
            operation=Operation.READ,
            risk_tier=RiskTier.MEDIUM,
            input_model=OrderStatusInput,
            output_model=OrderStatusOutput,
            handler=backend.get_order_status,
            allowed_roles=frozenset({"support_agent", "support_manager"}),
        )
    )
    registry.register(
        ToolDefinition(
            name="issue_refund",
            operation=Operation.WRITE,
            risk_tier=RiskTier.CRITICAL,
            input_model=RefundInput,
            output_model=RefundOutput,
            handler=backend.issue_refund,
            allowed_roles=frozenset({"support_agent", "support_manager"}),
            requires_approval=True,
            approval_roles=frozenset({"finance_manager"}),
            amount_limit=Decimal("500.00"),
        )
    )
    return ToolGateway(registry, PolicyEngine(), audit), backend, audit
