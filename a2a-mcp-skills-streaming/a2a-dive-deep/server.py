"""A2A servers for the two specialists.

    python server.py incident
    python server.py refund
"""
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))

import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from a2a.server.agent_execution import AgentExecutor
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import a2a_pb2 as a2a

from specialists import build_incident_graph, build_refund_graph

HOST = "127.0.0.1"
AGENTS = {
    "incident": {
        "port": 8001,
        "name": "Incident Triage Agent",
        "skill_id": "incident-triage",
        "description": "Classify a production incident. Does not change production.",
        "graph": build_incident_graph,
        "example": "Checkout is failing with payment errors.",
    },
    "refund": {
        "port": 8002,
        "name": "Refund Agent",
        "skill_id": "refund-check",
        "description": "Recommend a refund review for sample orders 1042-1045. Does not pay a refund.",
        "graph": build_refund_graph,
        "example": "Can I get a refund for order 1042?",
    },
}


def agent_message(text):
    return a2a.Message(
        message_id=str(uuid4()),
        role=a2a.ROLE_AGENT,
        parts=[a2a.Part(text=text)],
    )


class SpecialistExecutor(AgentExecutor):
    def __init__(self, role):
        self.role = role
        self.graph = AGENTS[role]["graph"]()

    async def execute(self, context, event_queue):
        task_id = context.task_id or str(uuid4())
        context_id = context.context_id or str(uuid4())
        updater = TaskUpdater(event_queue, task_id, context_id)
        await event_queue.enqueue_event(
            a2a.Task(
                id=task_id,
                context_id=context_id,
                status=a2a.TaskStatus(state=a2a.TASK_STATE_SUBMITTED),
                history=[context.message],
            )
        )
        try:
            await updater.update_status(
                a2a.TASK_STATE_WORKING,
                agent_message(f"{self.role} specialist started."),
            )
            result = await self.graph.ainvoke(
                {"request": context.get_user_input(), "answer": ""}
            )
            await updater.add_artifact(
                [a2a.Part(text=result["answer"])],
                name="answer",
                last_chunk=True,
            )
            await updater.complete(agent_message(f"{self.role} specialist finished."))
        except Exception as exc:
            await updater.update_status(
                a2a.TASK_STATE_FAILED,
                agent_message(f"{type(exc).__name__}: the specialist could not finish."),
            )

    async def cancel(self, context, event_queue):
        await TaskUpdater(event_queue, context.task_id, context.context_id).update_status(
            a2a.TASK_STATE_CANCELED,
            agent_message("Task cancelled."),
        )


def agent_card(role):
    spec = AGENTS[role]
    url = f"http://localhost:{spec['port']}/"
    return a2a.AgentCard(
        name=spec["name"],
        description=spec["description"],
        version="1.0.0",
        supported_interfaces=[
            a2a.AgentInterface(
                url=url,
                protocol_binding="JSONRPC",
                protocol_version="1.0",
            )
        ],
        capabilities=a2a.AgentCapabilities(streaming=True),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[
            a2a.AgentSkill(
                id=spec["skill_id"],
                name=spec["name"],
                description=spec["description"],
                tags=[role, "teaching"],
                examples=[spec["example"]],
            )
        ],
    )


def app(role):
    card = agent_card(role)
    handler = DefaultRequestHandler(
        agent_executor=SpecialistExecutor(role),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )

    async def health(request):
        return JSONResponse({"service": role, "ready": True})

    return Starlette(
        routes=[
            Route("/health", health),
            *create_agent_card_routes(card),
            *create_jsonrpc_routes(handler, "/"),
        ]
    )


if __name__ == "__main__":
    role = sys.argv[1] if len(sys.argv) > 1 else ""
    if role not in AGENTS:
        raise SystemExit("Usage: python server.py incident|refund")
    uvicorn.run(app(role), host=HOST, port=AGENTS[role]["port"], log_level="warning")
