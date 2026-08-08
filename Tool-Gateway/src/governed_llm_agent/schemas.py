from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProposedToolArguments(StrictModel):
    """Closed arg object — OpenAI json_schema requires additionalProperties: false."""

    tenant_id: str = Field(
        description=(
            "Tenant id named in the operator request text (e.g. tenant_acme). "
            "Copy it from free text when present; this is not authorization."
        )
    )
    order_id: str = Field(description="Order id referenced by the operator.")
    amount: str | None = Field(
        default=None,
        description="Decimal string amount. Required for issue_refund; omit for reads.",
    )
    reason: str | None = Field(
        default=None,
        description="Business reason. Required for issue_refund; omit for reads.",
    )


class ModelToolProposal(StrictModel):
    """Untrusted model output. Must never include actor identity or approvals."""

    tool_name: Literal["get_order_status", "issue_refund"] = Field(
        description="Registered tool to propose. Never invent new tool names."
    )
    arguments: ProposedToolArguments = Field(
        description=(
            "Tool arguments only. For get_order_status: tenant_id, order_id. "
            "For issue_refund: tenant_id, order_id, amount (string decimal), reason."
        )
    )
    rationale: str = Field(
        min_length=8,
        max_length=400,
        description="Brief business rationale for the proposed tool call.",
    )


class OutcomeNarration(StrictModel):
    """Customer-facing explanation of the gateway outcome."""

    message: str = Field(min_length=8, max_length=800)


class TrustedActor(StrictModel):
    """Identity derived from authentication context, never from the model."""

    actor_id: str
    role: str
    tenant_id: str
