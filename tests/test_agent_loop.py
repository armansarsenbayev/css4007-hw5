"""The model and tools loop, with the ScriptedChatModel test double."""

import json

import pytest
from langchain_core.messages import ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END
from langgraph.store.memory import InMemoryStore

from fake_model import ScriptedChatModel, answer, tool_call
from helpdesk.agent_graph import MAX_TOOL_ROUNDS, RunContext, build_agent_graph, route_after_agent

CONTEXT = RunContext(user_id="demo-user-a", thread_id="loop-test", status_profile="wifi_outage")
CONFIG = {"configurable": {"thread_id": "loop-test"}, "recursion_limit": 25}


@pytest.fixture(autouse=True)
def temp_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("HELPDESK_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("HELPDESK_TICKET_DIR", str(tmp_path / "tickets"))


def run(model):
    app = build_agent_graph(model, InMemorySaver(), InMemoryStore())
    nodes, final = [], None
    for mode, chunk in app.stream(
        {"messages": [("user", "Is Wi-Fi down?")]}, CONFIG, context=CONTEXT, stream_mode=["updates", "values"]
    ):
        if mode == "updates":
            nodes.extend(chunk)
        else:
            final = chunk
    return nodes, final


def test_tool_result_reaches_model_then_answer_ends():
    model = ScriptedChatModel(responses=[tool_call("check_service_status", service="wifi"), answer("Wi-Fi is down.")])
    nodes, final = run(model)

    assert nodes == ["load_user_memory", "agent", "tools", "agent"]
    # The second model call saw the ToolMessage produced by our tools node.
    tool_messages = [m for m in model.received[1] if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 1
    result = json.loads(tool_messages[0].content)
    assert result["status"] == "outage"
    assert result["status_profile"] == "wifi_outage"  # from the run context, not the model
    assert tool_messages[0].tool_call_id == final["messages"][1].tool_calls[0]["id"]
    assert final["messages"][-1].content == "Wi-Fi is down."
    assert final["tool_rounds"] == 1
    assert final["loop_limit_reached"] is False


def test_model_that_always_requests_a_tool_is_stopped():
    model = ScriptedChatModel(responses=[tool_call("find_instructions", topic="wifi")], repeat_last=True)
    nodes, final = run(model)

    assert nodes.count("tools") == MAX_TOOL_ROUNDS
    assert nodes[-1] == "loop_limit"
    assert final["loop_limit_reached"] is True
    assert final["tool_rounds"] == MAX_TOOL_ROUNDS
    # Every tool call has an answer, so the history is valid for the next turn.
    call_ids = {c["id"] for m in final["messages"] for c in getattr(m, "tool_calls", [])}
    answered = {m.tool_call_id for m in final["messages"] if isinstance(m, ToolMessage)}
    assert call_ids == answered


def test_unknown_tool_and_bad_arguments_do_not_crash():
    model = ScriptedChatModel(
        responses=[tool_call("delete_everything"), tool_call("find_instructions", topic="printer"), answer("Sorry.")]
    )
    nodes, final = run(model)
    errors = [json.loads(m.content) for m in final["messages"] if isinstance(m, ToolMessage)]
    assert all("error" in e for e in errors) and len(errors) == 2
    assert nodes[-1] == "agent"


def test_model_cannot_override_status_profile():
    model = ScriptedChatModel(
        responses=[tool_call("check_service_status", service="wifi", status_profile="normal"), answer("ok")]
    )
    _, final = run(model)
    result = json.loads(final["messages"][2].content)
    assert result["status_profile"] == "wifi_outage"


def test_route_after_agent_decisions():
    with_call = tool_call("find_instructions", topic="wifi")
    with_call.tool_calls[0]["id"] = "c1"
    assert route_after_agent({"messages": [with_call], "tool_rounds": 0}) == "tools"
    assert route_after_agent({"messages": [with_call], "tool_rounds": MAX_TOOL_ROUNDS}) == "loop_limit"
    assert route_after_agent({"messages": [answer("done")], "tool_rounds": 0}) == END
