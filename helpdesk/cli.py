"""Terminal helpdesk (Parts 2 and 3).

    python -m helpdesk.cli --user demo-user-a --thread s10 --status normal
    python -m helpdesk.cli --user demo-user-a --thread s10 --status normal --message "..."
    python -m helpdesk.cli --reset

user, thread and status profile are chosen here by the person running the
program and passed to the graph as run context. The model never chooses them.
"""

import argparse
import sys
from pathlib import Path

from helpdesk.agent_graph import RunContext, build_agent_graph
from helpdesk.data import status_profiles
from helpdesk.memory import open_memory, reset_storage, storage_dir
from helpdesk.model import load_env, make_model
from helpdesk.tracing import append_trace, run_agent_turn, summary_line


def run_one(app, message: str, context: RunContext, trace_path) -> None:
    event = run_agent_turn(app, message, context)
    print(f"Helpdesk: {event['final_reply']}")
    print(summary_line(event))
    if trace_path:
        append_trace(trace_path, event)


def main(argv=None) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    load_env()
    parser = argparse.ArgumentParser(description="Practice university IT helpdesk")
    parser.add_argument("--user", help="invented user id, for example demo-user-a")
    parser.add_argument("--thread", help="conversation id")
    parser.add_argument("--status", choices=status_profiles(), default="normal", help="status snapshot")
    parser.add_argument("--message", help="send one message and exit")
    parser.add_argument("--trace", type=Path, help="append each turn's trace to this JSON file")
    parser.add_argument("--reset", action="store_true", help="delete the memory databases and exit")
    args = parser.parse_args(argv)

    if args.reset:
        removed = reset_storage()
        print("Removed: " + (", ".join(removed) if removed else f"nothing in {storage_dir()}"))
        return
    if not args.user or not args.thread:
        parser.error("--user and --thread are required")

    context = RunContext(user_id=args.user, thread_id=args.thread, status_profile=args.status)
    model = make_model()
    with open_memory() as (saver, store):
        app = build_agent_graph(model, checkpointer=saver, store=store)
        if args.message is not None:
            run_one(app, args.message, context, args.trace)
            return
        print(f"Helpdesk for {args.user}, thread {args.thread}, status {args.status}. Type /quit to exit.")
        while True:
            try:
                text = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if text == "/quit":
                break
            if text:
                run_one(app, text, context, args.trace)


if __name__ == "__main__":
    main()
