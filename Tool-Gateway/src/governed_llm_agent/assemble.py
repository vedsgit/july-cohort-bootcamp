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
    return f"refund_{order_id}_{amount}_v1"


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
    # TODO 6: inject the trusted actor + request/trace IDs + idempotency key
    # and optional approval. Do NOT invent identity from model/free text.
    del actor, request_id, trace_id, idempotency_key, approval
    return {
        "tool_name": model_proposal.tool_name,
        "arguments": model_proposal.arguments.model_dump(mode="json", exclude_none=True),
        "actor": {
            "actor_id": "model_claimed_actor",
            "role": "finance_manager",
            "tenant_id": model_proposal.arguments.tenant_id,
        },
        "context": {
            "request_id": "missing",
            "trace_id": "missing",
            "idempotency_key": None,
        },
    }
