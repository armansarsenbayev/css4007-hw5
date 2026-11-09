"""Part 1 routing: rule order, case handling and the clarification variant."""

import pytest

from helpdesk.part1_graph import CLARIFY_QUESTION, build_graph, run_with_trace

README_CASES = [
    ("I cannot connect to Wi-Fi.", "wifi", "wifi_help"),
    ("I forgot my PASSWORD.", "password", "password_help"),
    ("My laptop screen is broken.", "other", "other_help"),
]
BOTH = "My Wi-Fi password does not work."


def route(variant: str, message: str) -> tuple[str, list[str]]:
    trace = run_with_trace(build_graph(variant), message)
    return trace["steps"][0]["update"]["category"], trace["nodes_visited"]


@pytest.mark.parametrize("variant", ["original", "with_clarification"])
@pytest.mark.parametrize("message,category,node", README_CASES)
@pytest.mark.parametrize("case", [str, str.upper, str.lower])
def test_single_topic_messages(variant, message, category, node, case):
    got_category, nodes = route(variant, case(message))
    assert got_category == category
    assert nodes == ["read_request", node]


@pytest.mark.parametrize("case", [str, str.upper, str.lower])
def test_both_topics_original_goes_to_wifi(case):
    # The Wi-Fi rule is checked first, so it wins in the original graph.
    category, nodes = route("original", case(BOTH))
    assert category == "wifi"
    assert nodes == ["read_request", "wifi_help"]


@pytest.mark.parametrize("case", [str, str.upper, str.lower])
def test_both_topics_changed_graph_asks(case):
    trace = run_with_trace(build_graph("with_clarification"), case(BOTH))
    assert trace["nodes_visited"] == ["read_request", "clarify_problem"]
    assert trace["steps"][0]["update"] == {"category": "both"}
    assert trace["final_reply"] == CLARIFY_QUESTION


def test_original_graph_has_no_clarify_node():
    assert "clarify_problem" not in build_graph("original").get_graph().nodes
    assert "clarify_problem" in build_graph("with_clarification").get_graph().nodes


def test_help_nodes_use_reference_data():
    trace = run_with_trace(build_graph("original"), "wifi")
    assert "GUIDE-WIFI" in trace["final_reply"]
    assert "Campus-Demo" in trace["final_reply"]
    # The original message is never changed by any node.
    assert all(step["state_after"]["message"] == "wifi" for step in trace["steps"])


def test_unknown_variant_raises():
    with pytest.raises(ValueError):
        build_graph("something_else")
