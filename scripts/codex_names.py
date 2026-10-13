"""Small, read-only conversation-name cache; no model calls or background worker."""
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
import uuid


def conversation_id(value):
    if not value:
        return None
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError):
        raise ValueError("codex_thread_id 必须是完整的 Codex 对话 UUID") from None


def current_conversation(explicit=None):
    return conversation_id(os.environ.get("CODEX_THREAD_ID") if explicit is None else explicit)


def identifiers(task):
    explicit = task.get("codex_thread_id")
    if explicit:
        return (conversation_id(explicit),), "record"
    # Older task IDs sometimes contain the full ID or its first UUID segment.
    # Only a unique metadata match is accepted; names, dates and PIDs are not evidence.
    parts = re.findall(r"(?<![a-zA-Z0-9])[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}(?![a-zA-Z0-9])|(?<![a-zA-Z0-9])[0-9a-fA-F]{8}(?![a-zA-Z0-9])", str(task.get("task_id", "")))
    return tuple(sorted({part.lower() for part in parts})), "task_id"


class TaskConversations:
    def __init__(self, codex_home=None, *, interval=10, clock=time.monotonic):
        self.home = Path(codex_home or os.environ.get("CODEX_HOME") or Path.home() / ".codex").resolve()
        self.interval, self.clock = interval, clock
        self.lock = threading.Lock()
        self.key, self.names, self.checked, self.error = None, {}, None, False

    def _read(self, keys):
        clauses, values = [], []
        for key in keys:
            if len(key) == 36:
                clauses.append("id = ?")
                values.append(key)
            else:
                clauses.append("(id >= ? AND id < ?)")
                values.extend((key, key + "g"))
        db = sqlite3.connect((self.home / "state_5.sqlite").as_uri() + "?mode=ro", uri=True, timeout=.25)
        try:
            # Read only display metadata, never history or message contents.
            return {key: name or title or key for key, name, title in db.execute(
                "SELECT id,name,title FROM threads WHERE " + " OR ".join(clauses), values)}
        finally:
            db.close()

    def enrich(self, tasks):
        bindings = []
        for task in tasks:
            try:
                keys, source = identifiers(task)
            except ValueError:
                keys, source = (), "invalid"
            bindings.append((task, keys, source))
        keys = tuple(sorted({key for _, values, _ in bindings for key in values}))
        with self.lock:
            stamp = self.clock()
            if keys != self.key or self.checked is None or stamp - self.checked >= self.interval:
                try:
                    self.names = self._read(keys) if keys else {}
                    self.error = False
                except (OSError, sqlite3.Error):
                    # Retain last known names, but visibly mark them as unverified.
                    self.names = {key: value for key, value in self.names.items() if any(key.startswith(k) for k in keys)}
                    self.error = True
                self.key, self.checked = keys, stamp
            result = []
            for task, values, source in bindings:
                matches = {key for key in self.names if any(key == v if len(v) == 36 else key.startswith(v) for v in values)}
                linked = next(iter(matches)) if len(matches) == 1 else values[0] if source == "record" else None
                result.append({**task, "codex_conversation": {
                    "id": linked, "name": self.names.get(linked), "source": source,
                    "status": "stale" if self.error and linked else "linked" if linked in self.names else "missing" if linked else "unlinked",
                }})
            return result
