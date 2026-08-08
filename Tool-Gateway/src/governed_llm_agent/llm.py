from __future__ import annotations

import json
import re
from typing import Protocol

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage

from .config import Settings
from .prompts import NARRATION_SYSTEM_PROMPT, PROPOSAL_SYSTEM_PROMPT
from .schemas import ModelToolProposal, OutcomeNarration, TrustedActor


class Proposer(Protocol):
    def propose(self, *, user_text: str, actor: TrustedActor) -> ModelToolProposal: ...


class Narrator(Protocol):
    def narrate(self, *, user_text: str, gateway_result: dict[str, object]) -> str: ...


class OpenAIProposer:
    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is required for live mode. "
                "Set GOVERNED_LLM_MODE=fake for offline demos."
            )
        model = init_chat_model(
            settings.openai_model,
            model_provider="openai",
            api_key=settings.openai_api_key,
            temperature=0,
        )
        self._structured = model.with_structured_output(ModelToolProposal)

    def propose(self, *, user_text: str, actor: TrustedActor) -> ModelToolProposal:
        # Do NOT pass trusted session tenant into the model prompt.
        # Identity arrives later via FrontendSession → assemble → gateway.
        # The model only sees free text (untrusted), so cross-tenant claims
        # in the request can surface in arguments and be denied by policy.
        del actor
        messages = [
            SystemMessage(content=PROPOSAL_SYSTEM_PROMPT),
            HumanMessage(content=f"Operator request:\n{user_text}"),
        ]
        result = self._structured.invoke(messages) # LLM Call to generate a proposal
        if isinstance(result, ModelToolProposal):
            return result
        return ModelToolProposal.model_validate(result)


class OpenAINarrator:
    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for live mode.")
        model = init_chat_model(
            settings.openai_model,
            model_provider="openai",
            api_key=settings.openai_api_key,
            temperature=0,
        )
        self._structured = model.with_structured_output(OutcomeNarration)

    def narrate(self, *, user_text: str, gateway_result: dict[str, object]) -> str:
        messages = [
            SystemMessage(content=NARRATION_SYSTEM_PROMPT),
            HumanMessage(
                content=(
                    f"Original request:\n{user_text}\n\n"
                    f"Gateway result JSON:\n{json.dumps(gateway_result, default=str)}"
                )
            ),
        ]
        result = self._structured.invoke(messages) # LLM call
        if isinstance(result, OutcomeNarration):
            return result.message
        return OutcomeNarration.model_validate(result).message


class FakeProposer:
    """Deterministic stand-in so the full graph can be demoed offline."""

    def propose(self, *, user_text: str, actor: TrustedActor) -> ModelToolProposal:
        lowered = user_text.lower()
        order_match = re.search(r"ord_[A-Za-z0-9]+", user_text)
        order_id = order_match.group(0) if order_match else "ord_A100"
        amount_match = re.search(r"\$?\s*(\d+(?:\.\d{1,2})?)", lowered)
        amount = amount_match.group(1) if amount_match else "120.00"
        # Simulate a model that copies a tenant claim from free text (untrusted).
        # Trusted tenant still arrives only via FrontendSession → actor.
        claimed_tenant = _claimed_tenant_from_text(user_text) or actor.tenant_id
        if "refund" in lowered:
            return ModelToolProposal(
                tool_name="issue_refund",
                arguments={
                    "tenant_id": claimed_tenant,
                    "order_id": order_id,
                    "amount": f"{float(amount):.2f}",
                    "reason": "Product arrived damaged and cannot be used",
                },
                rationale="Operator requested a refund for the referenced order.",
            )
        return ModelToolProposal(
            tool_name="get_order_status",
            arguments={
                "tenant_id": claimed_tenant,
                "order_id": order_id,
            },
            rationale="Operator asked for order status.",
        )


def _claimed_tenant_from_text(user_text: str) -> str | None:
    match = re.search(r"\btenant_[A-Za-z0-9]+\b", user_text)
    return match.group(0) if match else None


class FakeNarrator:
    def narrate(self, *, user_text: str, gateway_result: dict[str, object]) -> str:
        del user_text
        status = gateway_result.get("status")
        error = gateway_result.get("error") or {}
        if status == "succeeded":
            return f"Completed successfully. Result data: {gateway_result.get('data')}"
        if status == "approval_required":
            return (
                "The write is paused. Independent finance approval is required "
                "before the gateway will execute."
            )
        code = error.get("code", "unknown")
        message = error.get("message", "")
        return f"Request was not executed ({status}). Reason: {code}. {message}".strip()


def build_proposer(settings: Settings) -> Proposer:
    if settings.is_live:
        return OpenAIProposer(settings)
    return FakeProposer()


def build_narrator(settings: Settings) -> Narrator:
    if settings.is_live:
        return OpenAINarrator(settings)
    return FakeNarrator()
