from __future__ import annotations

from typing import Any
from uuid import uuid4

from .schemas import ModelToolProposal, TrustedActor


def new_request_ids() -> tuple[str, str]:
    request_id = f"request_{uuid4().hex[:8]}"
    trace_id = f"trace_{uuid4().hex[:10]}"
    return request_id, trace_id


def default_idempotency_key(tool_name: str, arguments: dict[str, Any]) -> str | None:
    if tool_name != "issue_refund":
        return None
    order_id = str(arguments.get("order_id", "unknown"))
    amount = str(arguments.get("amount") or "0")
    return f"refund_{order_id}_{amount}_v1" # encode as hex to avoid confusion with other characters

def assemble_gateway_proposal(
    *,
    model_proposal: ModelToolProposal,
    actor: TrustedActor,
    request_id: str,
    trace_id: str,
    idempotency_key: str | None,
    approval: dict[str, object] | None = None,
) -> dict[str, object]:
    """Merge untrusted model arguments with trusted identity and correlation IDs."""
    context: dict[str, object] = {
        "request_id": request_id,
        "trace_id": trace_id,
        "idempotency_key": idempotency_key,
    }
    if approval is not None:
        context["approval"] = approval

    return {
        "tool_name": model_proposal.tool_name,
        "arguments": model_proposal.arguments.model_dump(mode="json", exclude_none=True),
        "actor": actor.model_dump(mode="json"),
        "context": context,
    }
