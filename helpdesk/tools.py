"""Helpdesk tools.

Each tool is a plain Python function first, so it can be called and tested
without the agent. Below them are LangChain tool wrappers. Arguments marked
InjectedToolArg are hidden from the model's schema: the application supplies
them (status profile, user id, thread id, store), never the model.

CLI:
    python -m helpdesk.tools find_instructions wifi
    python -m helpdesk.tools check_service_status wifi --profile wifi_outage
    python -m helpdesk.tools prepare_ticket --category wifi --summary "..." --step "..." --step "..."
"""

import argparse
import json
import re
import secrets
import sys
from datetime import datetime
from typing import Annotated, Any, Literal, Optional

from langchain_core.tools import InjectedToolArg, tool

from helpdesk.data import load_helpdesk, load_service_status, load_ticket_template
from helpdesk.memory import display_path, ticket_dir

TOPICS = ("wifi", "password")
SERVICES = ("wifi", "account_recovery")
PREFERENCE_NAMESPACE = "users"
PREFERENCE_KEY = "preferences"

# Text that looks like a secret value. Mentioning a password problem is fine;
# giving the password or a code is not.
_SAFE_AFTER_IS = r"(?!not\b|wrong\b|incorrect\b|invalid\b|expired\b|rejected\b|locked\b|blocked\b|reset\b|broken\b|missing\b|unavailable\b|failing\b)"
SECRET_PATTERNS = [
    re.compile(r"\bpassword\s*[:=]", re.IGNORECASE),
    re.compile(r"\bpassword\s+is\s+" + _SAFE_AFTER_IS + r"\S+", re.IGNORECASE),
    re.compile(r"\brecovery\s+code\s*(?:[:=]|is\b)", re.IGNORECASE),
    re.compile(r"\bapi[\s_-]?key\b", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9_-]{4,}"),
]


# ---------- plain functions ----------

def find_instructions(topic: str) -> dict:
    """Return the local instructions for wifi or password."""
    instructions = load_helpdesk()["instructions"]
    if topic not in instructions:
        return {"error": f"Unknown topic {topic!r}.", "allowed": list(instructions)}
    guide = instructions[topic]
    return {
        "instruction_id": guide["instruction_id"],
        "title": guide["title"],
        "steps": list(guide["steps"]),
        "source": "data/helpdesk.json",
    }


def check_service_status(service: str, status_profile: str) -> dict:
    """Look up a service in the selected status snapshot. Never raises."""
    profiles = load_service_status()["profiles"]
    if status_profile not in profiles:
        return {"error": f"Unknown status profile {status_profile!r}.", "allowed": list(profiles)}
    snapshot = profiles[status_profile]
    if service not in snapshot:
        return {"error": f"Unknown service {service!r}.", "allowed": list(snapshot)}
    entry = snapshot[service]
    return {
        "service": service,
        "status": entry["status"],  # operational, outage or unknown, passed through as is
        "message": entry["message"],
        "status_profile": status_profile,
        "source": "data/service_status.json",
    }


def looks_like_secret(text: str) -> bool:
    return any(p.search(text) for p in SECRET_PATTERNS)


def new_ticket_id(now: Optional[datetime] = None) -> str:
    now = now or datetime.now()
    return f"TKT-{now:%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"


def prepare_ticket(
    category: str,
    summary: str,
    steps_tried: list[str],
    service_status: Optional[str] = None,
    *,
    user_id: str,
    thread_id: str,
    status_profile: str,
) -> dict:
    """Write a local ticket draft. Nothing is sent anywhere."""
    if category not in TOPICS:
        return {"error": f"Unknown category {category!r}.", "allowed": list(TOPICS)}

    summary = (summary or "").strip()
    steps = [s.strip() for s in (steps_tried or []) if s and s.strip()]
    missing = []
    if not summary:
        missing.append("summary")
    if not steps:
        missing.append("steps_tried")
    if missing:
        return {
            "needs_info": missing,
            "message": "No draft written. Ask the user for the missing details; do not invent them.",
        }

    if any(looks_like_secret(text) for text in [summary, *steps, service_status or ""]):
        return {
            "error": "The ticket text looks like it contains a password, recovery code or key. "
            "Secrets are not stored in tickets, so no draft was written. "
            "Ask the user to describe the problem without the secret."
        }

    ticket = dict(load_ticket_template()["ticket"])
    ticket_id = new_ticket_id()
    guide_id = load_helpdesk()["instructions"][category]["instruction_id"]
    ticket.update(
        {
            "ticket_id": ticket_id,
            "status": "draft",
            "user_id": user_id,
            "thread_id": thread_id,
            "category": category,
            "summary": summary,
            "steps_tried": steps,
            "service_status": (service_status or "").strip() or "not checked",
            "status_profile": status_profile,
            "reference_ids": [guide_id],
        }
    )
    folder = ticket_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{ticket_id}.json"
    path.write_text(json.dumps(ticket, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ticket_id": ticket_id, "file": display_path(path), "sent": False}


def save_user_preference(language: str, *, user_id: str, store) -> dict:
    """Save the reply language for this user only."""
    language = (language or "").strip()
    if not language:
        return {"error": "Language is empty; nothing saved."}
    store.put((PREFERENCE_NAMESPACE, user_id), PREFERENCE_KEY, {"language": language})
    return {"saved": True, "language": language, "scope": "this user, all conversations"}


def load_user_preference(store, user_id: str) -> Optional[dict]:
    item = store.get((PREFERENCE_NAMESPACE, user_id), PREFERENCE_KEY)
    return dict(item.value) if item else None


# ---------- LangChain tool wrappers (what the model sees) ----------

@tool("find_instructions")
def find_instructions_tool(topic: Literal["wifi", "password"]) -> dict:
    """Look up the local helpdesk instructions for a topic: 'wifi' or 'password'."""
    return find_instructions(topic)


@tool("check_service_status")
def check_service_status_tool(
    service: Literal["wifi", "account_recovery"],
    status_profile: Annotated[str, InjectedToolArg],
) -> dict:
    """Check the demo status of a service: 'wifi' or 'account_recovery' (used for password problems).
    Returns status 'operational', 'outage' or 'unknown'."""
    return check_service_status(service, status_profile)


@tool("prepare_ticket")
def prepare_ticket_tool(
    category: Literal["wifi", "password"],
    summary: str,
    steps_tried: list[str],
    user_id: Annotated[str, InjectedToolArg],
    thread_id: Annotated[str, InjectedToolArg],
    status_profile: Annotated[str, InjectedToolArg],
    service_status: Optional[str] = None,
) -> dict:
    """Save a local ticket draft (never sent). summary and steps_tried must come only from
    what the user said. service_status is the checked status, or omit it if not checked."""
    return prepare_ticket(
        category,
        summary,
        steps_tried,
        service_status,
        user_id=user_id,
        thread_id=thread_id,
        status_profile=status_profile,
    )


@tool("save_user_preference")
def save_user_preference_tool(
    language: str,
    user_id: Annotated[str, InjectedToolArg],
    store: Annotated[Any, InjectedToolArg],
) -> dict:
    """Remember the user's preferred reply language (for example 'Kazakh') for later conversations."""
    return save_user_preference(language, user_id=user_id, store=store)


HELPDESK_TOOLS = [
    find_instructions_tool,
    check_service_status_tool,
    prepare_ticket_tool,
    save_user_preference_tool,
]
TOOLS_BY_NAME = {t.name: t for t in HELPDESK_TOOLS}

# Which application values each tool needs. The tools node fills these in.
APP_ARGS = {
    "find_instructions": (),
    "check_service_status": ("status_profile",),
    "prepare_ticket": ("user_id", "thread_id", "status_profile"),
    "save_user_preference": ("user_id", "store"),
}


# ---------- CLI ----------

def main(argv=None) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Call a helpdesk tool directly, without the agent")
    sub = parser.add_subparsers(dest="tool", required=True)

    p = sub.add_parser("find_instructions")
    p.add_argument("topic")

    p = sub.add_parser("check_service_status")
    p.add_argument("service")
    p.add_argument("--profile", default="normal")

    p = sub.add_parser("prepare_ticket")
    p.add_argument("--category", required=True)
    p.add_argument("--summary", default="")
    p.add_argument("--step", action="append", default=[], dest="steps")
    p.add_argument("--service-status", default=None)
    p.add_argument("--user", default="demo-user-a")
    p.add_argument("--thread", default="manual")
    p.add_argument("--profile", default="normal")

    args = parser.parse_args(argv)
    if args.tool == "find_instructions":
        result = find_instructions(args.topic)
    elif args.tool == "check_service_status":
        result = check_service_status(args.service, args.profile)
    else:
        result = prepare_ticket(
            args.category,
            args.summary,
            args.steps,
            args.service_status,
            user_id=args.user,
            thread_id=args.thread,
            status_profile=args.profile,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
