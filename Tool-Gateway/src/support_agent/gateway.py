from __future__ import annotations

from pydantic import ValidationError

from .audit import AuditSink
from .contracts import Decision, ResultStatus, ToolError, ToolProposal, ToolResult
from .policy import PolicyEngine
from .registry import ToolRegistry


class ToolGateway:
    def __init__(
        self,
        registry: ToolRegistry,
        policy: PolicyEngine,
        audit: AuditSink,
    ) -> None:
        self.registry = registry
        self.policy = policy
        self.audit = audit

    def execute(self, raw_proposal: dict[str, object]) -> ToolResult:
        proposal = ToolProposal.model_validate(raw_proposal)
        tool = self.registry.get(proposal.tool_name)
        if tool is None:
            return self._result(
                proposal, ResultStatus.DENIED, "unknown_tool", "Tool is not registered"
            )

        # TODO 4: catch input validation errors and return an INVALID result.
        validated_input = tool.input_model.model_validate(proposal.arguments)
        decision = self.policy.evaluate(proposal, tool, validated_input)
        if decision.decision == Decision.DENY:
            return self._result(
                proposal,
                ResultStatus.DENIED,
                decision.reason_code,
                decision.explanation,
            )
        if decision.decision == Decision.REQUIRE_APPROVAL:
            return self._result(
                proposal,
                ResultStatus.APPROVAL_REQUIRED,
                decision.reason_code,
                decision.explanation,
            )

        raw_output = tool.handler(validated_input, proposal.context.idempotency_key)
        # TODO 5: validate the tool result before returning it to the agent.
        audit_id = self._audit(proposal, ResultStatus.SUCCEEDED.value, "executed")
        return ToolResult(
            status=ResultStatus.SUCCEEDED,
            data=raw_output,
            audit_id=audit_id,
        )

    def _result(
        self,
        proposal: ToolProposal,
        status: ResultStatus,
        reason_code: str,
        message: str,
    ) -> ToolResult:
        audit_id = self._audit(proposal, status.value, reason_code)
        return ToolResult(
            status=status,
            error=ToolError(code=reason_code, message=message),
            audit_id=audit_id,
        )

    def _audit(self, proposal: ToolProposal, outcome: str, reason_code: str) -> str:
        return self.audit.record(
            trace_id=proposal.context.trace_id,
            request_id=proposal.context.request_id,
            actor_id=proposal.actor.actor_id,
            tenant_id=proposal.actor.tenant_id,
            tool_name=proposal.tool_name,
            outcome=outcome,
            reason_code=reason_code,
        )
