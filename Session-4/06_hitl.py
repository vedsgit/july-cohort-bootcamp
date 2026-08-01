from typing import TypedDict
import uuid
import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import interrupt, Command
from langgraph.graph import StateGraph, START, END

class UserState(TypedDict):
    user_input: str
    approval_message: str

def human_node(state: UserState):
    print(f"Node started execution with state: {state}")
    value = interrupt("As per the analysis, the refund eligibility amount is $1000. Please approve or reject this amount.")
    print(f"User message/input: {value}")
    return {"approval_message": value}

conn = sqlite3.connect("checkpoint.db", check_same_thread=False)
memory = SqliteSaver(conn)

builder = StateGraph(UserState)
builder.add_node("human", human_node)

builder.add_edge(START, "human")
builder.add_edge("human", END)

graph = builder.compile(checkpointer=memory)

thread_id = str(uuid.uuid4())
print(f"Thread ID: {thread_id}")
result = graph.invoke({"user_input": "I want to refund my order"}, config={"configurable": {"thread_id": thread_id}})

print("Result of the graph execution:")
print(f"Result: {result}")

# result = graph.invoke(Command(resume="Accepted"), config={"configurable": {"thread_id": thread_id}})

# print("Result of the graph execution:")
# print(f"Result: {result}")
