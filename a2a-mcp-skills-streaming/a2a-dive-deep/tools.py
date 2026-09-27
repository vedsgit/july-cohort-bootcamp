from langchain_core.tools import tool

from a2a_client import call_a2a_agent


@tool
async def incident_triage_agent(
    incident: str,
) -> str:
    """
    Delegate production incident analysis to the
    specialist Incident Triage Agent.

    Use this when the user reports outages,
    errors, failures, latency, payment failures,
    checkout failures, or other production issues.
    """

    return await call_a2a_agent(
        agent_url="http://localhost:8001",
        request_text=incident,
    )


@tool
async def refund_agent(
    request: str,
) -> str:
    """
    Delegate customer refund requests to the
    specialist Refund Agent.

    Use this when the user wants a refund,
    refund eligibility check, payment reversal,
    or refund status.
    """

    return await call_a2a_agent(
        agent_url="http://localhost:8002",
        request_text=request,
    )