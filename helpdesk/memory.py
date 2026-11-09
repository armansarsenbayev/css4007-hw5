"""Storage settings for conversation memory, user memory and ticket drafts.

* HELPDESK_STORAGE_DIR (default local-storage) holds
  checkpoints.sqlite (conversation memory, keyed by thread_id) and
  user_memory.sqlite (user preferences, keyed by user_id).
* HELPDESK_TICKET_DIR (default outputs/tickets) holds local ticket drafts.

Relative paths are resolved from the repository root. The environment is
read on every call so tests can point it at a temporary folder.
"""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.store.sqlite import SqliteStore

from helpdesk.data import REPO_ROOT

CHECKPOINT_DB = "checkpoints.sqlite"
USER_MEMORY_DB = "user_memory.sqlite"


def _resolve(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def storage_dir() -> Path:
    return _resolve(os.environ.get("HELPDESK_STORAGE_DIR") or "local-storage")


def ticket_dir() -> Path:
    return _resolve(os.environ.get("HELPDESK_TICKET_DIR") or "outputs/tickets")


def display_path(path: Path) -> str:
    """Path relative to the repository root when possible, for logs and replies."""
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def open_saver() -> SqliteSaver:
    """Checkpointer for conversation state (one history per thread_id)."""
    folder = storage_dir()
    folder.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(folder / CHECKPOINT_DB, check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    return saver


def open_store() -> SqliteStore:
    """Key value store for user memory (namespace ("users", user_id)).

    The connection must be autocommit (isolation_level=None), otherwise
    SqliteStore fails with "cannot start a transaction within a transaction".
    """
    folder = storage_dir()
    folder.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(folder / USER_MEMORY_DB, check_same_thread=False, isolation_level=None)
    store = SqliteStore(conn)
    store.setup()
    return store


@contextmanager
def open_memory():
    """Open the saver and the store, and close both connections on exit."""
    saver = open_saver()
    store = open_store()
    try:
        yield saver, store
    finally:
        saver.conn.close()
        store.conn.close()


def reset_storage() -> list[str]:
    """Delete only the two memory databases (and their -wal/-shm files)."""
    folder = storage_dir()
    removed = []
    for name in (CHECKPOINT_DB, USER_MEMORY_DB):
        for suffix in ("", "-wal", "-shm"):
            path = folder / f"{name}{suffix}"
            if path.exists():
                path.unlink()
                removed.append(display_path(path))
    return removed
