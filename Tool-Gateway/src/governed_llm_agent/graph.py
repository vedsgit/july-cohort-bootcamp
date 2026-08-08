from __future__ import annotations

from typing import Any, Literal, TypedDict
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from support_agent.gateway import ToolGateway

from .assemble import (
    assemble_gateway_proposal,
    default_idempotency_key,
    new_request_ids,
)
from .llm import Narrator, Proposer
from .schemas import ModelToolProposal, TrustedActor


class AgentState(TypedDict, total=False):
    user_text: str
    actor: dict[str, str]
    request_id: str
    trace_id: str
    idempotency_key: str | None
    model_proposal: dict[str, Any] | None
    gateway_proposal: dict[str, Any] | None
    gateway_result: dict[str, Any] | None
    approval: dict[str, Any] | None
    assistant_message: str | None
    phase: str


def build_graph(*, gateway: ToolGateway, proposer: Proposer, narrator: Narrator):
    def propose_node(state: AgentState) -> dict[str, Any]:
        actor = TrustedActor.model_validate(state["actor"])
        request_id, trace_id = new_request_ids()
        proposal = proposer.propose(user_text=state["user_text"], actor=actor)
        idempotency_key = default_idempotency_key(
            proposal.tool_name,
            proposal.arguments.model_dump(mode="json", exclude_none=True),
        )
        return {
            "request_id": request_id,
            "trace_id": trace_id,
            "idempotency_key": idempotency_key,
            "model_proposal": proposal.model_dump(mode="json"),
            "phase": "proposed",
        }

    def assemble_node(state: AgentState) -> dict[str, Any]:
        model_proposal = ModelToolProposal.model_validate(state["model_proposal"])
        actor = TrustedActor.model_validate(state["actor"])
        proposal = assemble_gateway_proposal(
            model_proposal=model_proposal,
            actor=actor,
            request_id=state["request_id"],
            trace_id=state["trace_id"],
            idempotency_key=state.get("idempotency_key"),
            approval=state.get("approval"),
        )
        return {
            "gateway_proposal": proposal,
            "phase": "assembled",
        }

    def enforce_node(state: AgentState) -> dict[str, Any]:
        result = gateway.execute(state["gateway_proposal"])
        return {
            "gateway_result": result.model_dump(mode="json"),
            "phase": "enforced",
        }

    def await_approval_node(state: AgentState) -> dict[str, Any]:
        """Human-in-the-loop pause. Resume value becomes the approval payload."""
        arguments = (state.get("model_proposal") or {}).get("arguments", {})
        payload = {
            "message": "Finance approval required before executing this write.",
            "model_proposal": state.get("model_proposal"),
            "gateway_result": state.get("gateway_result"),
            "suggested_approval": {
                "approved_by": "manager_7",
                "approver_role": "finance_manager",
                "approved_amount": arguments.get("amount", "0.00"),
                "expires_at_offset_minutes": 15,
            },
        }
        approval = interrupt(payload)
        if not isinstance(approval, dict):
            raise TypeError("Resume value must be an approval dict")
        return {
            "approval": approval,
            "phase": "approved",
        }

    def narrate_node(state: AgentState) -> dict[str, Any]:
        message = narrator.narrate(
            user_text=state["user_text"],
            gateway_result=state["gateway_result"] or {},
        )
        return {
            "assistant_message": message,
            "phase": "done",
        }

    def after_enforce(state: AgentState) -> Literal["await_approval", "narrate"]:
        result = state.get("gateway_result") or {}
        if result.get("status") == "approval_required" and not state.get("approval"):
            return "await_approval"
        return "narrate"

    builder = StateGraph(AgentState)
    builder.add_node("propose", propose_node)
    builder.add_node("assemble", assemble_node)
    builder.add_node("enforce", enforce_node)
    builder.add_node("await_approval", await_approval_node)
    builder.add_node("narrate", narrate_node)

    builder.add_edge(START, "propose")
    builder.add_edge("propose", "assemble")
    builder.add_edge("assemble", "enforce")
    builder.add_conditional_edges(
        "enforce",
        after_enforce,
        {
            "await_approval": "await_approval",
            "narrate": "narrate",
        },
    )
    builder.add_edge("await_approval", "assemble")
    builder.add_edge("narrate", END)

    return builder.compile(checkpointer=InMemorySaver())


def new_thread_id() -> str:
    return f"thread_{uuid4().hex[:12]}"
