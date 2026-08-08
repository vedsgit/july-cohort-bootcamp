from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from pydantic import BaseModel

from .contracts import Decision, PolicyDecision, ToolProposal
from .registry import ToolDefinition

POLICY_VERSION = "policy.v1"


class PolicyEngine:
    """Deterministic policy. Natural-language instructions never reach this layer."""

    version: str = POLICY_VERSION

    def evaluate(
        self,
        proposal: ToolProposal,
        tool: ToolDefinition,
        validated_input: BaseModel,
    ) -> PolicyDecision:
        if proposal.actor.role not in tool.allowed_roles:
            return self._deny("role_not_allowed", "Actor role cannot invoke this tool")

        input_tenant = getattr(validated_input, "tenant_id", None)
        if input_tenant != proposal.actor.tenant_id:
            return self._deny("tenant_mismatch", "Actor and resource tenants differ")

        if tool.amount_limit is not None:
            amount = getattr(validated_input, "amount", Decimal("0"))
            if amount > tool.amount_limit:
                return self._deny(
                    "amount_over_limit",
                    "Requested amount exceeds tool policy",
                )

        if tool.requires_approval:
            if not proposal.context.idempotency_key:
                return self._deny(
                    "idempotency_required",
                    "Write operations require an idempotency key",
                )

            approval = proposal.context.approval
            if approval is None:
                return PolicyDecision(
                    decision=Decision.REQUIRE_APPROVAL,
                    reason_code="approval_missing",
                    explanation="A valid independent approval is required",
                )
            if approval.approver_role not in tool.approval_roles:
                return self._deny(
                    "approver_role_invalid",
                    "Approver role is not authorized",
                )
            if approval.approved_by == proposal.actor.actor_id:
                return self._deny(
                    "self_approval",
                    "Requester cannot approve their own action",
                )
            if not approval.is_valid_at(datetime.now(timezone.utc)):
                return self._deny("approval_expired", "Approval has expired")
            amount = getattr(validated_input, "amount", Decimal("0"))
            if amount > approval.approved_amount:
                return self._deny(
                    "approval_amount_exceeded",
                    "Amount exceeds approval",
                )

        return PolicyDecision(
            decision=Decision.ALLOW,
            reason_code="policy_allow",
            explanation="All deterministic policy checks passed",
        )

    @staticmethod
    def _deny(code: str, explanation: str) -> PolicyDecision:
        return PolicyDecision(
            decision=Decision.DENY,
            reason_code=code,
            explanation=explanation,
        )
