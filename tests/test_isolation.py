"""Users and conversations stay separate."""

import pytest
from langchain_core.messages import SystemMessage

from fake_model import ScriptedChatModel, answer, tool_call
from helpdesk.agent_graph import RunContext, build_agent_graph
from helpdesk.memory import open_memory
from helpdesk.tools import load_user_preference


@pytest.fixture()
def memory(tmp_path, monkeypatch):
    monkeypatch.setenv("HELPDESK_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("HELPDESK_TICKET_DIR", str(tmp_path / "tickets"))
    with open_memory() as (saver, store):
        yield saver, store


def turn(memory, model, user, thread, text):
    saver, store = memory
    app = build_agent_graph(model, saver, store)
    config = {"configurable": {"thread_id": thread}}
    before = app.get_state(config).values.get("messages", [])
    out = app.invoke({"messages": [("user", text)]}, config, context=RunContext(user, thread, "normal"))
    return before, out


def system_prompt(model) -> str:
    first = model.received[0][0]
    assert isinstance(first, SystemMessage)
    return first.content


def save_kazakh(memory):
    model = ScriptedChatModel(responses=[tool_call("save_user_preference", language="Kazakh"), answer("Saved.")])
    turn(memory, model, "demo-user-a", "a1", "Please remember that I prefer replies in Kazakh.")


def test_other_user_does_not_see_preference(memory):
    save_kazakh(memory)
    model_b = ScriptedChatModel(responses=[answer("No preference has been recorded.")])
    before, out = turn(memory, model_b, "demo-user-b", "b1", "Have I told you a preferred language?")

    assert before == []
    assert out["user_preference"] is None
    assert "Saved user preference: none recorded" in system_prompt(model_b)
    assert "Kazakh" not in system_prompt(model_b)
    assert load_user_preference(memory[1], "demo-user-b") is None


def test_new_thread_same_user_loads_preference_but_not_messages(memory):
    save_kazakh(memory)
    model = ScriptedChatModel(responses=[answer("Қазақ тілі.")])
    before, out = turn(memory, model, "demo-user-a", "a2", "Which language did I ask you to use?")

    assert before == []  # the new thread starts empty
    assert [m.content for m in out["messages"]] == ["Which language did I ask you to use?", "Қазақ тілі."]
    assert out["user_preference"] == {"language": "Kazakh"}
    assert '"language": "Kazakh"' in system_prompt(model)
    # The old thread still has its own messages.
    saver, store = memory
    app = build_agent_graph(ScriptedChatModel(responses=[]), saver, store)
    old_messages = app.get_state({"configurable": {"thread_id": "a1"}}).values["messages"]
    assert old_messages[0].content == "Please remember that I prefer replies in Kazakh."


def test_same_thread_keeps_earlier_messages(memory):
    turn(memory, ScriptedChatModel(responses=[answer("Noted.")]), "demo-user-a", "s10", "I enabled Wi-Fi.")
    model = ScriptedChatModel(responses=[answer("You enabled Wi-Fi.")])
    before, _ = turn(memory, model, "demo-user-a", "s10", "Which steps did I already try?")
    assert [m.content for m in before] == ["I enabled Wi-Fi.", "Noted."]
    assert any(getattr(m, "content", "") == "I enabled Wi-Fi." for m in model.received[0])
