"""Start both A2A specialists, then ask the LangGraph coordinator.

From this folder:

    python demo.py
    python demo.py "Checkout is failing with payment errors."
    python demo.py --live "Can I get a refund for order 1043?"

The coordinator does not import the specialists. tools.py calls them over A2A.
"""
import argparse
import asyncio
import os
import socket
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx
from langchain_core.messages import HumanMessage

from coordinator import build_coordinator
from server import AGENTS, HOST

HERE = Path(__file__).resolve().parent
EXAMPLES = [
    "Checkout is failing with payment errors and high latency.",
    "Can I get a refund for order 1042?",
    "Can I get a refund for order 1043?",
]


def _port_is_free(port):
    with socket.socket() as sock:
        sock.settimeout(0.2)
        return sock.connect_ex((HOST, port)) != 0


async def _wait_until_ready(ports):
    ports = list(ports)
    async with httpx.AsyncClient(timeout=2, trust_env=False) as http:
        for _ in range(40):
            ready = True
            for port in ports:
                try:
                    response = await http.get(f"http://{HOST}:{port}/health")
                    ready = ready and response.status_code == 200
                except httpx.HTTPError:
                    ready = False
            if ready:
                return
            await asyncio.sleep(0.25)
    raise RuntimeError("A specialist did not become ready. Read the server output above.")


def _show(result):
    for message in result["messages"]:
        if message.type == "human":
            continue
        if message.type == "ai" and message.tool_calls:
            names = ", ".join(call["name"] for call in message.tool_calls)
            print(f"Coordinator: {message.content}  [{names}]")
        elif message.type == "tool":
            print(f"Tool {message.name} returned:\n{message.content}")
        elif message.type == "ai" and message.content:
            print(f"Coordinator reply:\n{message.content}")


async def run(prompts, mode):
    blocked = [spec["port"] for spec in AGENTS.values() if not _port_is_free(spec["port"])]
    if blocked:
        raise SystemExit(f"Port already in use: {', '.join(map(str, blocked))}. Stop the previous demo first.")

    processes = []
    for role in AGENTS:
        processes.append(
            subprocess.Popen(
                [os.path.abspath(sys.executable), str(HERE / "server.py"), role],
                cwd=HERE,
            )
        )
    try:
        await _wait_until_ready(spec["port"] for spec in AGENTS.values())
        graph = build_coordinator(mode)
        print(f"Mode: {mode}")
        print("Incident specialist  http://localhost:8001")
        print("Refund specialist    http://localhost:8002")
        for prompt in prompts:
            print("\n" + "=" * 72)
            print("You:", prompt)
            result = await graph.ainvoke({"messages": [HumanMessage(content=prompt)]})
            _show(result)
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


def main():
    parser = argparse.ArgumentParser(description="A2A dive-deep with LangGraph")
    parser.add_argument("prompt", nargs="*", help="One request. Omit to run the sample requests.")
    parser.add_argument("--live", action="store_true", help="Let the model choose the tool.")
    args = parser.parse_args()
    prompts = [" ".join(args.prompt)] if args.prompt else EXAMPLES
    try:
        asyncio.run(run(prompts, "live" if args.live else "rehearsal"))
    except Exception as exc:
        raise SystemExit(f"Demo stopped: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
