from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Operation(StrEnum):
    READ = "read"
    WRITE = "write"


class RiskTier(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Decision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


class ResultStatus(StrEnum):
    SUCCEEDED = "succeeded"
    DENIED = "denied"
    APPROVAL_REQUIRED = "approval_required"
    INVALID = "invalid"
    FAILED = "failed"


class Actor(StrictModel):
    actor_id: str = Field(min_length=3, max_length=80)
    role: str = Field(min_length=3, max_length=50)
    tenant_id: str = Field(pattern=r"^tenant_[a-z0-9_]+$")


class Approval(StrictModel):
    approved_by: str = Field(min_length=3, max_length=80)
    approver_role: str = Field(min_length=3, max_length=50)
    approved_amount: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    expires_at: datetime

    def is_valid_at(self, now: datetime) -> bool:
        expiry = self.expires_at
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        return expiry > now


class ExecutionContext(StrictModel):
    request_id: str = Field(min_length=8, max_length=100)
    trace_id: str = Field(min_length=8, max_length=100)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=100)
    approval: Approval | None = None


class ToolProposal(StrictModel):
    tool_name: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,128}$")
    arguments: dict[str, Any]
    actor: Actor
    context: ExecutionContext


class RefundInput(StrictModel):
    tenant_id: str = Field(pattern=r"^tenant_[a-z0-9_]+$")
    order_id: str = Field(pattern=r"^ord_[A-Za-z0-9]+$")
    amount: Decimal = Field(gt=0, le=Decimal("5000"), max_digits=10, decimal_places=2)
    reason: str = Field(min_length=8, max_length=240)

    @field_validator("reason")
    @classmethod
    def reject_control_language(cls, value: str) -> str:
        normalized = value.lower()
        blocked = ("ignore previous", "system override", "bypass policy")
        if any(marker in normalized for marker in blocked):
            raise ValueError("reason contains control-like instructions")
        return value


class RefundOutput(StrictModel):
    refund_id: str = Field(pattern=r"^ref_[A-Za-z0-9]+$")
    order_id: str
    amount: Decimal
    status: str


class OrderStatusInput(StrictModel):
    tenant_id: str = Field(pattern=r"^tenant_[a-z0-9_]+$")
    order_id: str = Field(pattern=r"^ord_[A-Za-z0-9]+$")


class OrderStatusOutput(StrictModel):
    order_id: str
    status: str
    refundable_balance: Decimal


class PolicyDecision(StrictModel):
    decision: Decision
    reason_code: str
    explanation: str


class ToolError(StrictModel):
    code: str
    message: str
    retryable: bool = False


class ToolResult(StrictModel):
    status: ResultStatus
    data: dict[str, Any] | None = None
    error: ToolError | None = None
    audit_id: str
