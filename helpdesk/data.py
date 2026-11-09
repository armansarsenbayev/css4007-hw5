"""Load the fictional helpdesk fixtures from data/.

Paths are resolved from the repository root, so the program works
no matter which directory it is started from.
"""

import json
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"


def _load(name: str) -> dict:
    path = DATA_DIR / name
    with path.open(encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=None)
def load_helpdesk() -> dict:
    """Instructions, topic aliases, topic to service mapping, scope, ticket policy."""
    return _load("helpdesk.json")


@lru_cache(maxsize=None)
def load_service_status() -> dict:
    """The four named status snapshots."""
    return _load("service_status.json")


@lru_cache(maxsize=None)
def load_ticket_template() -> dict:
    """The field layout for a local ticket draft."""
    return _load("ticket_template.json")


@lru_cache(maxsize=None)
def load_scenarios() -> dict:
    """The S01 to S14 demonstration inputs."""
    return _load("scenarios.json")


def status_profiles() -> list[str]:
    """Names of the available status snapshots."""
    return list(load_service_status()["profiles"].keys())
