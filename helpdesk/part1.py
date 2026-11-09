"""Command line entry for Part 1: python -m helpdesk.part1 --variant original --message "..."."""

import argparse
import json
import sys
from pathlib import Path

from helpdesk.part1_graph import VARIANTS, build_graph, run_with_trace


def print_trace(trace: dict) -> None:
    print(f"Message: {trace['message']}")
    print("Node order: START -> " + " -> ".join(trace["nodes_visited"]) + " -> END")
    for i, step in enumerate(trace["steps"], start=1):
        print(f"\n[{i}] {step['node']}")
        print(f"    update:     {json.dumps(step['update'], ensure_ascii=False)}")
        print(f"    state after:")
        for key, value in step["state_after"].items():
            shown = str(value).replace("\n", "\n                 ")
            print(f"      {key}: {shown}")
        print(f"    next node:  {step['next_node_chosen_by_edge']}")
    print(f"\nReply:\n{trace['final_reply']}")


def main(argv=None) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Part 1 rule based helpdesk graph")
    parser.add_argument("--variant", choices=VARIANTS, default="original")
    parser.add_argument("--message", help="message to route")
    parser.add_argument("--save", type=Path, help="write the trace JSON to this path")
    parser.add_argument("--mermaid", action="store_true", help="print the generated Mermaid diagram")
    args = parser.parse_args(argv)

    app = build_graph(args.variant)
    if args.mermaid:
        print(app.get_graph().draw_mermaid())
    if args.message is None:
        if not args.mermaid:
            parser.error("--message is required unless --mermaid is given")
        return

    trace = run_with_trace(app, args.message)
    trace["graph_variant"] = args.variant
    print_trace(trace)
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nTrace saved to {args.save}")


if __name__ == "__main__":
    main()
