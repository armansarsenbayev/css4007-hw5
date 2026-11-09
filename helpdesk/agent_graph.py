"""Parts 2 and 3: the model and tools graph with memory.

START -> load_user_memory -> agent -> route_after_agent
    tools      (tool calls, rounds below the limit) -> agent
    loop_limit (tool calls, limit reached)          -> END
    END        (no tool calls)

The model only requests tools. The tools node below is my own code: it
validates each request, adds the application values from the run context
and runs the Python function.
"""

import json
from dataclasses import dataclass
from typing import Annotated, Optional, TypedDict

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.runtime import Runtime

from helpdesk.data import load_helpdesk
from helpdesk.tools import APP_ARGS, HELPDESK_TOOLS, TOOLS_BY_NAME, load_user_preference

MAX_TOOL_ROUNDS = 4
RECURSION_LIMIT = 25  # LangGraph's own step limit, a second safety net

ASK_DETAILS = "What problem are you having, and what have you already tried?"
LOOP_LIMIT_REPLY = (
    f"I stopped after {MAX_TOOL_ROUNDS} rounds of tool calls without reaching an answer. "
    "How would you like to continue?"
)


@dataclass
class RunContext:
    """Values chosen by the person running the program, never by the model."""

    user_id: str
    thread_id: str
    status_profile: str


class AgentState(TypedDict, total=False):
    messages: Annotated[list, add_messages]  # appended to, not replaced
    user_preference: Optional[dict]  # loaded from user memory each turn
    tool_rounds: int  # tool rounds in the current turn
    loop_limit_reached: bool


def build_system_prompt(user_preference: Optional[dict]) -> str:
    """Built on every call; it is not stored in the checkpoint."""
    scope = "; ".join(load_helpdesk()["scope"])
    saved = json.dumps(user_preference, ensure_ascii=False) if user_preference else "none recorded"
    return f"""You are a practice university IT helpdesk. All data is fictional. Your scope: {scope}.

Instructions:
- To give instructions, call find_instructions. Do not write steps from memory.
- For password problems check service account_recovery. For Wi-Fi check service wifi.
- Service status has three different results: operational, outage, unknown. Unknown is never operational and never a confirmed outage. Never invent a repair time.
- If the user makes a ticket conditional on the status, follow the condition exactly:
  * operational: prepare the ticket.
  * outage: do not prepare it, and say why.
  * unknown: do not prepare it. Say the status could not be determined and ask whether they want a draft noting that the status could not be checked.
- The ticket summary and steps_tried must come only from what the user said in this conversation. Do not add troubleshooting the user did not mention. If details are missing, ask: "{ASK_DETAILS}"
- After a ticket is written, give the ticket id and file name and say that nothing was sent.
- Never ask for or store passwords or recovery codes.

Memory:
- If the user asks you to remember a language preference, call save_user_preference, then reply in that language.
- If a saved preference is given below, reply in that language. If there is none, reply in English.
- Use earlier messages of this conversation to resolve references like "that" or "the steps I tried".
- You know nothing about other users or other conversations. If asked about a preference or a previous problem that is not in this conversation or in the saved preference, say that none has been recorded.

Saved user preference: {saved}"""


def build_agent_graph(model, checkpointer=None, store=None):
    """Compile the agent graph. model is any chat model that supports bind_tools."""
    model_with_tools = model.bind_tools(HELPDESK_TOOLS)

    def load_user_memory(state: AgentState, runtime: Runtime[RunContext]) -> dict:
        """Read this user's saved preference and reset the per turn counters."""
        preference = None
        if runtime.store is not None:
            preference = load_user_preference(runtime.store, runtime.context.user_id)
        return {"user_preference": preference, "tool_rounds": 0, "loop_limit_reached": False}

    def agent(state: AgentState) -> dict:
        """Ask the model for the next step: a tool request or a final answer."""
        system = SystemMessage(build_system_prompt(state.get("user_preference")))
        response = model_with_tools.invoke([system, *state["messages"]])
        return {"messages": [response]}

    def tools(state: AgentState, runtime: Runtime[RunContext]) -> dict:
        """Run every tool the model requested, with values from the run context."""
        app_values = {
            "user_id": runtime.context.user_id,
            "thread_id": runtime.context.thread_id,
            "status_profile": runtime.context.status_profile,
            "store": runtime.store,
        }
        results = []
        for call in state["messages"][-1].tool_calls:
            name = call["name"]
            if name not in TOOLS_BY_NAME:
                result = {"error": f"Unknown tool {name!r}.", "allowed": list(TOOLS_BY_NAME)}
            else:
                # The model may not set application values, so drop them if it tried.
                args = {k: v for k, v in (call.get("args") or {}).items() if k not in app_values}
                args.update({k: app_values[k] for k in APP_ARGS[name]})
                try:
                    result = TOOLS_BY_NAME[name].invoke(args)
                except Exception as exc:  # bad arguments must not crash the graph
                    result = {"error": f"Invalid arguments for {name}: {exc}"}
            results.append(
                ToolMessage(
                    content=json.dumps(result, ensure_ascii=False),
                    tool_call_id=call["id"],
                    name=name,
                )
            )
        return {"messages": results, "tool_rounds": state.get("tool_rounds", 0) + 1}

    def loop_limit(state: AgentState) -> dict:
        """Stop safely. Unanswered tool calls get a 'not run' result so the history stays valid."""
        skipped = [
            ToolMessage(
                content=json.dumps({"error": "Not run: tool round limit reached."}),
                tool_call_id=call["id"],
                name=call["name"],
            )
            for call in state["messages"][-1].tool_calls
        ]
        return {"messages": [*skipped, AIMessage(LOOP_LIMIT_REPLY)], "loop_limit_reached": True}

    graph = StateGraph(AgentState, context_schema=RunContext)
    graph.add_node("load_user_memory", load_user_memory)
    graph.add_node("agent", agent)
    graph.add_node("tools", tools)
    graph.add_node("loop_limit", loop_limit)
    graph.add_edge(START, "load_user_memory")
    graph.add_edge("load_user_memory", "agent")
    graph.add_conditional_edges("agent", route_after_agent, ["tools", "loop_limit", END])
    graph.add_edge("tools", "agent")
    graph.add_edge("loop_limit", END)
    return graph.compile(checkpointer=checkpointer, store=store)


def route_after_agent(state: AgentState) -> str:
    """Conditional edge after the model. The loop limit is enforced here."""
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        if state.get("tool_rounds", 0) < MAX_TOOL_ROUNDS:
            return "tools"
        return "loop_limit"
    return END
