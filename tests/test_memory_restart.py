"""Memory survives a real process restart.

Subprocess 1 runs one turn (the fake model saves a preference) and exits.
Subprocess 2 opens the same storage folder and reads the thread and the
preference back. Nothing is shared in RAM between the two.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

FIRST_PROCESS = """
import os
from fake_model import ScriptedChatModel, answer, tool_call
from helpdesk.agent_graph import RunContext, build_agent_graph
from helpdesk.memory import open_memory

model = ScriptedChatModel(responses=[tool_call("save_user_preference", language="Kazakh"), answer("Saved.")])
with open_memory() as (saver, store):
    app = build_agent_graph(model, saver, store)
    app.invoke(
        {"messages": [("user", "Please remember that I prefer replies in Kazakh. My issue is Wi-Fi.")]},
        {"configurable": {"thread_id": "restart-t"}},
        context=RunContext("demo-user-a", "restart-t", "normal"),
    )
print(os.getpid())
"""

SECOND_PROCESS = """
import json, os
from fake_model import ScriptedChatModel
from helpdesk.agent_graph import build_agent_graph
from helpdesk.memory import open_memory
from helpdesk.tools import load_user_preference

with open_memory() as (saver, store):
    app = build_agent_graph(ScriptedChatModel(responses=[]), saver, store)
    state = app.get_state({"configurable": {"thread_id": "restart-t"}}).values
    print(json.dumps({
        "pid": os.getpid(),
        "messages": [m.content for m in state.get("messages", [])],
        "preference": load_user_preference(store, "demo-user-a"),
    }))
"""


def run_child(code: str, env: dict) -> str:
    done = subprocess.run(
        [sys.executable, "-c", code], cwd=REPO_ROOT, env=env, capture_output=True, text=True, encoding="utf-8"
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.strip().splitlines()[-1]


def test_conversation_and_preference_survive_restart(tmp_path):
    env = dict(os.environ)
    env["HELPDESK_STORAGE_DIR"] = str(tmp_path / "storage")
    env["HELPDESK_TICKET_DIR"] = str(tmp_path / "tickets")
    env["PYTHONPATH"] = os.pathsep.join([str(REPO_ROOT), str(REPO_ROOT / "tests")])

    first_pid = int(run_child(FIRST_PROCESS, env))
    assert (tmp_path / "storage" / "checkpoints.sqlite").exists()
    assert (tmp_path / "storage" / "user_memory.sqlite").exists()

    second = json.loads(run_child(SECOND_PROCESS, env))
    assert second["pid"] != first_pid
    assert second["messages"][0].startswith("Please remember that I prefer replies in Kazakh")
    assert second["messages"][-1] == "Saved."
    assert second["preference"] == {"language": "Kazakh"}
