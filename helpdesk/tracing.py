"""Run one turn and build its trace, and write scenario logs.

Every value in a trace comes from what actually happened in the run:
the stream of node updates, the checkpoint before the turn and the
tool results. Nothing is guessed.
"""

import json
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage
from langgraph.graph import END

from helpdesk.agent_graph import RECURSION_LIMIT, RunContext

SOURCE_CONVERSATION = "conversation memory"
SOURCE_USER = "user memory"
SOURCE_REFERENCE = "reference file: data/helpdesk.json"


def message_text(message: BaseMessage) -> str:
    """Plain text of a message, also when the provider returns content blocks."""
    content = message.content
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "".join(parts)


def to_jsonable(value: Any) -> Any:
    """Turn messages and other values into plain JSON data."""
    if isinstance(value, BaseMessage):
        data = {"type": value.type, "content": message_text(value)}
        if getattr(value, "tool_calls", None):
            data["tool_calls"] = [{"name": c["name"], "args": c["args"]} for c in value.tool_calls]
        if value.type == "tool":
            data["name"] = value.name
            data["tool_call_id"] = value.tool_call_id
        return data
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    return value


def run_agent_turn(app, message: str, context: RunContext) -> dict:
    """Send one user message through the agent graph and return its trace."""
    config = {"configurable": {"thread_id": context.thread_id}, "recursion_limit": RECURSION_LIMIT}
    messages_before = len(app.get_state(config).values.get("messages", []))

    steps, requests, results = [], [], []
    user_memory = None
    final_state: dict = {}
    rounds_done = 0
    for mode, chunk in app.stream(
        {"messages": [("user", message)]}, config, context=context, stream_mode=["updates", "values"]
    ):
        if mode == "values":
            final_state = chunk
            continue
        for node, update in chunk.items():
            update = update or {}
            steps.append({"node": node, "update": to_jsonable(update)})
            if node == "load_user_memory":
                user_memory = update.get("user_preference")
            elif node == "agent":
                for msg in update.get("messages", []):
                    for call in getattr(msg, "tool_calls", []) or []:
                        requests.append({"round": rounds_done + 1, "name": call["name"], "args": call["args"]})
            elif node == "tools":
                rounds_done += 1
                for msg in update.get("messages", []):
                    try:
                        result = json.loads(message_text(msg))
                    except json.JSONDecodeError:
                        result = message_text(msg)
                    results.append({"name": msg.name, "result": result})

    # route_after_agent is an edge, not a node, so its choice is the next node we saw.
    for i, step in enumerate(steps):
        step["next_node_chosen_by_edge"] = steps[i + 1]["node"] if i + 1 < len(steps) else END

    final_reply = ""
    for msg in reversed(final_state.get("messages", [])):
        if isinstance(msg, AIMessage):
            final_reply = message_text(msg)
            break

    names_run = {r["name"] for r in results}
    sources = []
    if messages_before > 0:
        sources.append(SOURCE_CONVERSATION)
    if user_memory:
        sources.append(SOURCE_USER)
    if "find_instructions" in names_run:
        sources.append(SOURCE_REFERENCE)
    if "check_service_status" in names_run:
        sources.append(f"status snapshot: {context.status_profile}")

    ticket_files = [
        r["result"]["file"]
        for r in results
        if r["name"] == "prepare_ticket" and isinstance(r["result"], dict) and "file" in r["result"]
    ]
    return {
        "user_id": context.user_id,
        "thread_id": context.thread_id,
        "message": message,
        "nodes_visited": [s["node"] for s in steps],
        "steps": steps,
        "model_tool_requests": requests,
        "tool_results": results,
        "memory_read": {
            "conversation_messages_before_turn": messages_before,
            "user_memory": user_memory,
        },
        "sources": sources,
        "final_reply": final_reply,
        "ticket_file": ticket_files[-1] if ticket_files else None,
        "tool_rounds": final_state.get("tool_rounds", 0),
        "loop_limit_reached": bool(final_state.get("loop_limit_reached", False)),
    }


def summary_line(event: dict) -> str:
    """One line per turn for the terminal."""
    tools = ", ".join(r["name"] for r in event.get("tool_results", [])) or "none"
    sources = ", ".join(event.get("sources", [])) or "none"
    line = f"[trace] nodes: {' > '.join(event['nodes_visited'])} | tools: {tools} | sources: {sources}"
    if event.get("ticket_file"):
        line += f" | ticket: {event['ticket_file']}"
    if event.get("loop_limit_reached"):
        line += " | LOOP LIMIT REACHED"
    return line


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def append_trace(path: Path, event: dict) -> None:
    """Append one turn to a JSON list file."""
    data = read_json(path, default=[])
    data.append(event)
    write_json(path, data)
