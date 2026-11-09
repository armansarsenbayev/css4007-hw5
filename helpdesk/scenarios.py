"""Run the S01 to S14 demonstrations from data/scenarios.json.

    python -m helpdesk.scenarios S06
    python -m helpdesk.scenarios all

The events of a scenario are split into segments at every restart_process
event. Each segment runs in its own new Python process:

    python -m helpdesk.scenarios --segment S11 0
    python -m helpdesk.scenarios --segment S11 1

The parent waits for one child to exit before starting the next, so a later
segment can only know earlier messages through the files in local-storage/.
Each child writes a partial trace with its process id; the parent merges them
into outputs/<ID>.json.
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime

from dotenv import load_dotenv

from helpdesk.data import REPO_ROOT, load_scenarios
from helpdesk.memory import display_path, reset_storage, storage_dir, ticket_dir
from helpdesk.tracing import read_json, write_json

OUTPUT_DIR = REPO_ROOT / "outputs"


def get_scenario(scenario_id: str) -> dict:
    for scenario in load_scenarios()["scenarios"]:
        if scenario["id"] == scenario_id:
            return scenario
    raise SystemExit(f"Unknown scenario {scenario_id!r}")


def split_segments(events: list[dict]) -> list[dict]:
    """Split events at every restart_process event."""
    segments = [{"after_restart": False, "events": []}]
    for event in events:
        if event["action"] == "restart_process":
            segments.append(
                {
                    "after_restart": True,
                    "preserve_local_storage": event.get("preserve_local_storage", True),
                    "events": [],
                }
            )
        else:
            segments[-1]["events"].append(event)
    return segments


def segment_file(scenario_id: str, index: int):
    return storage_dir() / "segments" / f"{scenario_id}-{index}.json"


def remove_old_tickets(thread_ids: set[str]) -> list[str]:
    """Delete ticket drafts from an earlier run of the same scenario threads."""
    removed = []
    folder = ticket_dir()
    if not folder.exists():
        return removed
    for path in folder.glob("TKT-*.json"):
        try:
            ticket = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if ticket.get("thread_id") in thread_ids:
            path.unlink()
            removed.append(display_path(path))
    return removed


# ---------- child process: run one segment ----------

def run_segment(scenario_id: str, index: int) -> None:
    scenario = get_scenario(scenario_id)
    segment = split_segments(scenario["events"])[index]
    pid = os.getpid()
    events = []

    if scenario["part"] == 1:
        # Part 1 needs no model and no API key, so the model module is never imported.
        from helpdesk.part1_graph import build_graph, run_with_trace

        app = build_graph(scenario.get("graph_variant") or "original")
        for event in segment["events"]:
            trace = run_with_trace(app, event["message"])
            events.append({"user_id": event["user_id"], "thread_id": event["thread_id"], **trace})
            print(f"  [pid {pid}] {event['message']} -> {' > '.join(trace['nodes_visited'])}")
    else:
        from helpdesk.agent_graph import RunContext, build_agent_graph
        from helpdesk.memory import open_memory
        from helpdesk.model import make_model
        from helpdesk.tracing import run_agent_turn, summary_line

        model = make_model()
        with open_memory() as (saver, store):
            app = build_agent_graph(model, checkpointer=saver, store=store)
            for event in segment["events"]:
                context = RunContext(
                    user_id=event["user_id"],
                    thread_id=event["thread_id"],
                    status_profile=scenario["status_profile"],
                )
                trace = run_agent_turn(app, event["message"], context)
                events.append(trace)
                print(f"  [pid {pid}] {event['user_id']}/{event['thread_id']}: {event['message']}")
                print(f"    Helpdesk: {trace['final_reply']}")
                print(f"    {summary_line(trace)}")

    result = {
        "process_id": pid,
        "after_restart": segment["after_restart"],
        "events": events,
    }
    if segment["after_restart"]:
        result["preserve_local_storage"] = segment["preserve_local_storage"]
    write_json(segment_file(scenario_id, index), result)


# ---------- parent process: run a whole scenario ----------

def run_scenario(scenario_id: str) -> dict:
    scenario = get_scenario(scenario_id)
    print(f"\n=== {scenario['id']}: {scenario['title']} (part {scenario['part']}, status {scenario['status_profile']})", flush=True)

    log = {
        "scenario": scenario["id"],
        "title": scenario["title"],
        "part": scenario["part"],
        "status_profile": scenario["status_profile"],
    }
    if scenario["part"] == 1:
        log["graph_variant"] = scenario.get("graph_variant") or "original"
    log["command"] = f"python -m helpdesk.scenarios {scenario['id']}"
    if scenario["part"] != 1:
        from helpdesk.model import model_info

        info = model_info()
        log["model"] = {"name": info["name"], "provider": info["provider"]}
    log["started_at"] = datetime.now().isoformat(timespec="seconds")

    if scenario.get("reset_before"):
        log["reset_before"] = {
            "removed_memory_files": reset_storage(),
            "removed_old_ticket_drafts": remove_old_tickets(
                {e["thread_id"] for e in scenario["events"] if "thread_id" in e}
            ),
        }

    segments = []
    for index, _ in enumerate(split_segments(scenario["events"])):
        path = segment_file(scenario["id"], index)
        if path.exists():
            path.unlink()
        # A new Python process for every segment; wait for it to exit.
        subprocess.run(
            [sys.executable, "-m", "helpdesk.scenarios", "--segment", scenario["id"], str(index)],
            check=True,
            cwd=REPO_ROOT,
        )
        segments.append(read_json(path))
        path.unlink()
    log["segments"] = segments
    log["parent_process_id"] = os.getpid()

    out = OUTPUT_DIR / f"{scenario['id']}.json"
    write_json(out, log)
    print(f"  log: {display_path(out)}")
    return log


def main(argv=None) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv(REPO_ROOT / ".env")  # storage paths; the model module is not imported here
    os.environ.setdefault("LANGSMITH_TRACING", "false")
    parser = argparse.ArgumentParser(description="Run the supplied scenarios")
    parser.add_argument("scenario", nargs="?", help="scenario id such as S06, or all")
    parser.add_argument("--segment", nargs=2, metavar=("ID", "INDEX"), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.segment:
        run_segment(args.segment[0], int(args.segment[1]))
        return
    if not args.scenario:
        parser.error("give a scenario id or all")

    if args.scenario.lower() == "all":
        ids = [s["id"] for s in load_scenarios()["scenarios"]]
    else:
        ids = [args.scenario.upper()]
    failed = []
    for scenario_id in ids:
        try:
            run_scenario(scenario_id)
        except subprocess.CalledProcessError as exc:
            print(f"  {scenario_id} failed: child process exited with code {exc.returncode}")
            failed.append(scenario_id)
    if failed:
        raise SystemExit(f"Failed scenarios: {', '.join(failed)}")


if __name__ == "__main__":
    main()
