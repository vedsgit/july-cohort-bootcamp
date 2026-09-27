"""LangGraph coordinator.

The agent node chooses a LangChain tool. The tool node runs it.
Those tools are the only path to the specialists, and they speak A2A.
"""
import os
from pathlib import Path
from uuid import uuid4

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from tools import incident_triage_agent, refund_agent

TOOLS = [incident_triage_agent, refund_agent]

SYSTEM = """You are a support coordinator.
You do not investigate incidents or decide refunds yourself.
Call incident_triage_agent for outages, errors, failures, latency, and checkout problems.
Call refund_agent for refunds, eligibility, and payment reversals.
Reply with the specialist's answer. Do not change its decision, and do not claim a refund was paid."""


def _load_env():
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _latest_text(state: MessagesState) -> str:
    content = state["messages"][-1].content
    if isinstance(content, str):
        return content
    return str(content)


def _tool_call(name, argument, text):
    return {
        "name": name,
        "args": {argument: text},
        "id": f"call_{uuid4().hex[:8]}",
        "type": "tool_call",
    }


def rehearsal_agent(state: MessagesState) -> dict:
    """Keyword stand-in for the model, so the demo runs with no API key."""
    last = state["messages"][-1]
    if isinstance(last, ToolMessage):
        return {"messages": [AIMessage(content=last.content)]}

    text = _latest_text(state)
    lowered = text.lower()
    if any(word in lowered for word in ("refund", "reversal", "money back")):
        return {
            "messages": [
                AIMessage(
                    content="Handing this to the refund specialist over A2A.",
                    tool_calls=[_tool_call("refund_agent", "request", text)],
                )
            ]
        }
    if any(word in lowered for word in ("outage", "error", "fail", "latency", "incident", "down", "checkout")):
        return {
            "messages": [
                AIMessage(
                    content="Handing this to the incident specialist over A2A.",
                    tool_calls=[_tool_call("incident_triage_agent", "incident", text)],
                )
            ]
        }
    return {
        "messages": [
            AIMessage(
                content=(
                    "Tell me about a production incident or a refund request. "
                    "I will hand it to the matching specialist over A2A."
                )
            )
        ]
    }


def _live_model():
    _load_env()
    key = os.getenv("OPENAI_API_KEY")
    model_name = os.getenv("OPENAI_MODEL")
    if not key or not model_name:
        raise ValueError(
            "Live mode needs OPENAI_API_KEY and OPENAI_MODEL in the environment or .env."
        )
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(model=model_name, api_key=key, temperature=0).bind_tools(TOOLS)


def build_coordinator(mode="rehearsal"):
    if mode == "live":
        model = _live_model()

        def agent(state: MessagesState) -> dict:
            messages = state["messages"]
            if not messages or not isinstance(messages[0], SystemMessage):
                messages = [SystemMessage(content=SYSTEM), *messages]
            return {"messages": [model.invoke(messages)]}
    elif mode == "rehearsal":
        agent = rehearsal_agent
    else:
        raise ValueError("mode must be rehearsal or live")

    graph = StateGraph(MessagesState)
    graph.add_node("agent", agent)
    graph.add_node("tools", ToolNode(TOOLS))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition)
    graph.add_edge("tools", "agent")
    return graph.compile()
