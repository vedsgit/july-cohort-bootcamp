from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from langgraph.types import Command

from support_agent.factory import build_gateway

from .config import Settings, load_settings
from .fixtures import FrontendSession, default_frontend_session
from .graph import build_graph, new_thread_id
from .llm import build_narrator, build_proposer
from .schemas import TrustedActor

_UNSET: Any = object()


def build_app(
    settings: Settings | None = None,
    *,
    audit_log_path: str | Path | None = _UNSET,
    idempotency_store_path: str | Path | None = _UNSET,
):
    settings = settings or load_settings()
    gateway_kwargs: dict[str, Any] = {}
    if audit_log_path is not _UNSET:
        gateway_kwargs["audit_log_path"] = audit_log_path
    if idempotency_store_path is not _UNSET:
        gateway_kwargs["idempotency_store_path"] = idempotency_store_path
    gateway, backend, audit = build_gateway(**gateway_kwargs)
    graph = build_graph(
        gateway=gateway,
        proposer=build_proposer(settings),
        narrator=build_narrator(settings),
    )
    return {
        "settings": settings,
        "graph": graph,
        "gateway": gateway,
        "backend": backend,
        "audit": audit,
        "audit_log_path": str(audit.path) if audit.path else None,
        "idempotency_store_path": (
            str(backend.idempotency_store_path)
            if backend.idempotency_store_path
            else None
        ),
    }


def finance_approval_from_amount(amount: str, *, minutes: int = 15) -> dict[str, object]:
    return {
        "approved_by": "manager_7",
        "approver_role": "finance_manager",
        "approved_amount": amount,
        "expires_at": (
            datetime.now(timezone.utc) + timedelta(minutes=minutes)
        ).isoformat(),
    }


def _extract_interrupt_value(result: dict[str, Any]) -> dict[str, Any] | None:
    interrupts = result.get("__interrupt__")
    if not interrupts:
        return None
    first = interrupts[0]
    value = getattr(first, "value", first)
    return value if isinstance(value, dict) else {"raw": value}


def _session_from_actor(actor: TrustedActor) -> FrontendSession:
    return FrontendSession(
        actor_id=actor.actor_id,
        role=actor.role,
        tenant_id=actor.tenant_id,
        session_id=f"sess_{actor.actor_id}",
    )


def run_text_request(
    user_text: str,
    *,
    session: FrontendSession | None = None,
    actor: TrustedActor | None = None,
    auto_approve: bool = True,
    settings: Settings | None = None,
    app: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Full enterprise path:
    frontend session + operator text → LLM proposal → assemble → gateway → HITL → narrate.

    `session.tenant_id` is auth input from the frontend (like a logged-in UI).
    Free text must never replace that tenant.
    """
    app = app or build_app(settings)
    graph = app["graph"]

    if session is not None:
        frontend = session
        trusted = actor or frontend.to_trusted_actor()
    elif actor is not None:
        trusted = actor
        frontend = _session_from_actor(actor)
    else:
        frontend = default_frontend_session()
        trusted = frontend.to_trusted_actor()

    thread_id = new_thread_id()
    config = {"configurable": {"thread_id": thread_id}}

    result = graph.invoke(
        {
            "user_text": user_text,
            "actor": trusted.model_dump(mode="json"),
            "approval": None,
            "model_proposal": None,
            "gateway_proposal": None,
            "gateway_result": None,
            "assistant_message": None,
            "phase": "started",
        },
        config=config,
    )

    interrupted = _extract_interrupt_value(result)
    if interrupted and auto_approve:
        suggested = interrupted.get("suggested_approval", {})
        amount = str(suggested.get("approved_amount", "0.00"))
        minutes = int(suggested.get("expires_at_offset_minutes", 15))
        approval = finance_approval_from_amount(amount, minutes=minutes)
        if suggested.get("approved_by"):
            approval["approved_by"] = suggested["approved_by"]
        if suggested.get("approver_role"):
            approval["approver_role"] = suggested["approver_role"]
        result = graph.invoke(Command(resume=approval), config=config)
        interrupted = None

    return {
        "thread_id": thread_id,
        "user_text": user_text,
        "session": {
            "session_id": frontend.session_id,
            "actor_id": frontend.actor_id,
            "role": frontend.role,
            "tenant_id": frontend.tenant_id,
        },
        "actor": trusted.model_dump(mode="json"),
        "model_proposal": result.get("model_proposal"),
        "gateway_proposal": result.get("gateway_proposal"),
        "gateway_result": result.get("gateway_result"),
        "assistant_message": result.get("assistant_message"),
        "phase": result.get("phase"),
        "interrupted": interrupted,
        "refund_side_effects": app["backend"].refund_side_effect_count,
        "audit_events": len(app["audit"].events),
        "audit_log_path": app.get("audit_log_path"),
        "idempotency_store_path": app.get("idempotency_store_path"),
        "mode": app["settings"].mode,
    }
