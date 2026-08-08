from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from .audit import AuditSink
from .contracts import (
    Decision,
    ResultStatus,
    ToolError,
    ToolProposal,
    ToolResult,
)
from .errors import ToolBoundaryError
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
        try:
            proposal = ToolProposal.model_validate(raw_proposal)
        except ValidationError as exc:
            return self._untrusted_rejection(raw_proposal, "proposal_invalid", str(exc))

        tool = self.registry.get(proposal.tool_name)
        if tool is None:
            return self._result(
                proposal,
                ResultStatus.DENIED,
                "unknown_tool",
                "Tool is not registered",
            )

        try:
            validated_input = tool.input_model.model_validate(proposal.arguments)
        except ValidationError as exc:
            return self._result(
                proposal,
                ResultStatus.INVALID,
                "input_invalid",
                str(exc),
            )

        decision = self.policy.evaluate(proposal, tool, validated_input)
        if decision.decision == Decision.DENY:
            return self._result(
                proposal,
                ResultStatus.DENIED,
                decision.reason_code,
                decision.explanation,
                details={"decision": decision.decision.value},
            )
        if decision.decision == Decision.REQUIRE_APPROVAL:
            return self._result(
                proposal,
                ResultStatus.APPROVAL_REQUIRED,
                decision.reason_code,
                decision.explanation,
                details={"decision": decision.decision.value},
            )

        try:
            raw_output = tool.handler(
                validated_input,
                proposal.context.idempotency_key,
            )
            validated_output = tool.output_model.model_validate(raw_output)
        except ToolBoundaryError as exc:
            return self._result(
                proposal,
                ResultStatus.FAILED,
                exc.code,
                exc.message,
            )
        except (ValidationError, ValueError) as exc:
            return self._result(
                proposal,
                ResultStatus.FAILED,
                "execution_failed",
                str(exc),
            )

        audit_id = self._audit(
            proposal,
            outcome=ResultStatus.SUCCEEDED.value,
            reason_code="executed",
            details={
                "decision": Decision.ALLOW.value,
                "idempotency_key": proposal.context.idempotency_key,
            },
        )
        return ToolResult(
            status=ResultStatus.SUCCEEDED,
            data=validated_output.model_dump(mode="json"),
            audit_id=audit_id,
        )

    def _result(
        self,
        proposal: ToolProposal,
        status: ResultStatus,
        reason_code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> ToolResult:
        audit_id = self._audit(
            proposal,
            outcome=status.value,
            reason_code=reason_code,
            details=details,
        )
        return ToolResult(
            status=status,
            error=ToolError(code=reason_code, message=message),
            audit_id=audit_id,
        )

    def _untrusted_rejection(
        self,
        raw: dict[str, object],
        reason_code: str,
        message: str,
    ) -> ToolResult:
        actor = raw.get("actor") if isinstance(raw.get("actor"), dict) else {}
        context = raw.get("context") if isinstance(raw.get("context"), dict) else {}
        audit_id = self.audit.record(
            trace_id=str(context.get("trace_id", "untrusted")),
            request_id=str(context.get("request_id", "untrusted")),
            actor_id=str(actor.get("actor_id", "untrusted")),
            tenant_id=str(actor.get("tenant_id", "untrusted")),
            tool_name=str(raw.get("tool_name", "untrusted")),
            outcome=ResultStatus.INVALID.value,
            reason_code=reason_code,
            details={"policy_version": self.policy.version},
        )
        return ToolResult(
            status=ResultStatus.INVALID,
            error=ToolError(code=reason_code, message=message),
            audit_id=audit_id,
        )

    def _audit(
        self,
        proposal: ToolProposal,
        *,
        outcome: str,
        reason_code: str,
        details: dict[str, Any] | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "policy_version": self.policy.version,
            "idempotency_key": proposal.context.idempotency_key,
        }
        if details:
            payload.update(details)
        return self.audit.record(
            trace_id=proposal.context.trace_id,
            request_id=proposal.context.request_id,
            actor_id=proposal.actor.actor_id,
            tenant_id=proposal.actor.tenant_id,
            tool_name=proposal.tool_name,
            outcome=outcome,
            reason_code=reason_code,
            details=payload,
        )
