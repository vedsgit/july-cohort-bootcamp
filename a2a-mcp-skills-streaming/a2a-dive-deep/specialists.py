"""One-node LangGraph specialists. They never talk to each other.

The coordinator reaches them only through A2A. These graphs are the
code behind the two agent servers.
"""
import re
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

# Same sample orders as the main lab. This specialist only recommends.
# refund_executed stays false.
ORDERS = {
    "1042": {"age_days": 10, "paid_inr": 18000, "requested_inr": 18000, "refunded_inr": 0},
    "1043": {"age_days": 10, "paid_inr": 18000, "requested_inr": 18000, "refunded_inr": 18000},
    "1044": {"age_days": 45, "paid_inr": 18000, "requested_inr": 18000, "refunded_inr": 0},
    "1045": {"age_days": 8, "paid_inr": 18000, "requested_inr": 9000, "refunded_inr": 9000},
}
REFUND_WINDOW_DAYS = 30


class SpecialistState(TypedDict):
    request: str
    answer: str


def triage(state: SpecialistState) -> dict:
    text = state["request"].lower()
    if any(word in text for word in ("outage", "down", "500", "checkout", "payment")):
        severity = "high"
    elif any(word in text for word in ("latency", "slow", "timeout")):
        severity = "medium"
    else:
        severity = "low"
    return {
        "answer": (
            "Incident triage specialist\n"
            f"Severity: {severity}\n"
            f"Report: {state['request']}\n"
            "Next step: keep the incident open for the on-call human. "
            "This agent does not restart services or change production."
        )
    }


def refund(state: SpecialistState) -> dict:
    match = re.search(r"\b(104[2-5])\b", state["request"])
    if not match:
        return {
            "answer": (
                "Refund specialist\n"
                "Decision: INCOMPLETE\n"
                "Ask again with a sample order id: 1042, 1043, 1044, or 1045.\n"
                "refund_executed: false"
            )
        }

    order_id = match.group(1)
    order = ORDERS[order_id]
    remaining = order["paid_inr"] - order["refunded_inr"]
    if order["age_days"] > REFUND_WINDOW_DAYS:
        decision = "BLOCKED"
        reason = (
            f"Order {order_id} is {order['age_days']} days old. "
            f"The policy window is {REFUND_WINDOW_DAYS} days."
        )
    elif remaining <= 0 or order["requested_inr"] > remaining:
        decision = "BLOCKED"
        reason = (
            f"Order {order_id} requested INR {order['requested_inr']:,}. "
            f"Remaining refundable value is INR {remaining:,}."
        )
    else:
        decision = "READY_FOR_REVIEW"
        reason = (
            f"Order {order_id} requested INR {order['requested_inr']:,}. "
            f"Remaining refundable value is INR {remaining:,}, "
            f"and the order is {order['age_days']} days old."
        )
    return {
        "answer": (
            "Refund specialist\n"
            f"Decision: {decision}\n"
            f"{reason}\n"
            "refund_executed: false\n"
            "A human still has to review this. This agent does not pay a refund."
        )
    }


def _compile(node):
    graph = StateGraph(SpecialistState)
    graph.add_node("work", node)
    graph.add_edge(START, "work")
    graph.add_edge("work", END)
    return graph.compile()


def build_incident_graph():
    return _compile(triage)


def build_refund_graph():
    return _compile(refund)
