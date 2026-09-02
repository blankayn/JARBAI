import json
import threading
from datetime import datetime
from pathlib import Path

STORE = Path(__file__).resolve().parents[2] / "memory.json"


class Memory:
    """Conversation turns, kept across restarts.

    Both UIs build their own Router, so a plain in-memory list meant the
    dashboard and the voice loop forgot each other's turns. One JSON store,
    shared by every process, fixes that: restart JARBAI or switch UIs and the
    conversation continues.

    Writing on every turn is safe here - it is one small line appended a
    handful of times a minute, fsync-free, onto a user's own disk.
    """

    def __init__(self, max_turns=10, path=None):
        self.max_turns = max_turns
        self.path = Path(path) if path else STORE
        self._lock = threading.Lock()
        self.turns = []
        self._load()

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                self.turns = [
                    t for t in data
                    if isinstance(t, dict) and t.get("role") and t.get("content")
                ]
        except (OSError, ValueError):
            self.turns = []
        self._trim()

    def _trim(self):
        if len(self.turns) > self.max_turns:
            self.turns = self.turns[-self.max_turns:]

    def _save(self):
        try:
            self.path.write_text(
                json.dumps(self.turns[-self.max_turns:], indent=1), encoding="utf-8"
            )
        except OSError:
            pass          # read-only disk, OneDrive sync hiccup - keep going

    def add(self, role, content):
        with self._lock:
            self.turns.append({"role": role, "content": content})
            self._trim()
            self._save()

    def messages(self):
        with self._lock:
            return list(self.turns)

    def clear(self):
        with self._lock:
            self.turns = []
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass
