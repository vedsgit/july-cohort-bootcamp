from pydantic import BaseModel

from .contracts import Decision, PolicyDecision, ToolProposal
from .registry import ToolDefinition

POLICY_VERSION = "policy.v1"


class PolicyEngine:
    version: str = POLICY_VERSION

    def evaluate(
        self,
        proposal: ToolProposal,
        tool: ToolDefinition,
        validated_input: BaseModel,
    ) -> PolicyDecision:
        # TODO 2: replace unconditional allow with deterministic checks for:
        # role, tenant, amount limit, idempotency key, independent approval,
        # approver role, approval expiry, and approved amount.
        del proposal, tool, validated_input
        return PolicyDecision(
            decision=Decision.ALLOW,
            reason_code="unsafe_allow",
            explanation="Starter intentionally allows every valid-shaped request",
        )
