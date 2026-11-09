"""Part 1: a rule based helpdesk graph with no model.

Two variants:
* original: Wi-Fi rule first, then password, else other.
* with_clarification: a message with both topics goes to clarify_problem.
"""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from helpdesk.data import load_helpdesk

VARIANTS = ("original", "with_clarification")
CLARIFY_QUESTION = "Is the problem connecting to Wi-Fi, or recovering your account password?"


class HelpdeskState(TypedDict, total=False):
    message: str  # the user's original message, never changed
    category: str  # wifi, password, other, or both (changed variant only)
    reply: str  # text produced by one help node


def _mentions(text: str, topic: str) -> bool:
    """True if the lowercased text contains any alias of the topic."""
    aliases = load_helpdesk()["topic_aliases"][topic]
    return any(alias in text for alias in aliases)


def _categorise(message: str, with_clarification: bool) -> str:
    text = message.lower()
    has_wifi = _mentions(text, "wifi")
    has_password = _mentions(text, "password")
    if with_clarification and has_wifi and has_password:
        return "both"
    if has_wifi:
        return "wifi"
    if has_password:
        return "password"
    return "other"


def _make_read_request(with_clarification: bool):
    def read_request(state: HelpdeskState) -> dict:
        """Read the message and write only the category."""
        return {"category": _categorise(state["message"], with_clarification)}

    return read_request


def _instruction_reply(topic: str) -> str:
    guide = load_helpdesk()["instructions"][topic]
    lines = [f"{guide['title']} ({guide['instruction_id']})"]
    lines += [f"{i}. {step}" for i, step in enumerate(guide["steps"], start=1)]
    return "\n".join(lines)


def wifi_help(state: HelpdeskState) -> dict:
    return {"reply": _instruction_reply("wifi")}


def password_help(state: HelpdeskState) -> dict:
    return {"reply": _instruction_reply("password")}


def other_help(state: HelpdeskState) -> dict:
    scope = "; ".join(load_helpdesk()["scope"])
    return {
        "reply": (
            "Does your problem concern Wi-Fi or a password? "
            f"This practice helpdesk covers: {scope}."
        )
    }


def clarify_problem(state: HelpdeskState) -> dict:
    return {"reply": CLARIFY_QUESTION}


def route_by_category(state: HelpdeskState) -> str:
    """Conditional edge: reads only category and returns the next node name."""
    return {
        "wifi": "wifi_help",
        "password": "password_help",
        "both": "clarify_problem",
    }.get(state["category"], "other_help")


def build_graph(variant: str = "original"):
    """Build and compile the Part 1 graph for the chosen variant."""
    if variant not in VARIANTS:
        raise ValueError(f"Unknown variant {variant!r}; choose one of {VARIANTS}")
    with_clarification = variant == "with_clarification"

    graph = StateGraph(HelpdeskState)
    graph.add_node("read_request", _make_read_request(with_clarification))
    graph.add_node("wifi_help", wifi_help)
    graph.add_node("password_help", password_help)
    graph.add_node("other_help", other_help)
    targets = ["wifi_help", "password_help", "other_help"]
    if with_clarification:
        graph.add_node("clarify_problem", clarify_problem)
        targets.append("clarify_problem")

    graph.add_edge(START, "read_request")
    graph.add_conditional_edges("read_request", route_by_category, targets)
    for node in targets:
        graph.add_edge(node, END)
    return graph.compile()


def run_with_trace(app, message: str) -> dict:
    """Run one message and record each node's update and the state after it."""
    steps = []
    initial_state = None
    for mode, chunk in app.stream({"message": message}, stream_mode=["updates", "values"]):
        if mode == "updates":
            for node, update in chunk.items():
                steps.append({"node": node, "update": update})
        elif mode == "values":
            if not steps:
                initial_state = dict(chunk)  # input state before any node ran
            else:
                steps[-1]["state_after"] = dict(chunk)

    # The edge function is not a node, so record its decision ourselves.
    for i, step in enumerate(steps):
        step["next_node_chosen_by_edge"] = steps[i + 1]["node"] if i + 1 < len(steps) else "END"

    final = steps[-1]["state_after"] if steps else {}
    return {
        "message": message,
        "initial_state": initial_state,
        "nodes_visited": [s["node"] for s in steps],
        "steps": steps,
        "final_reply": final.get("reply"),
    }
