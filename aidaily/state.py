"""Persistent memory of what we've already covered.

Without this the pipeline re-posts the same story every morning for as long as
it stays in a feed. Stored as a plain JSON file so it can be committed back to
the repo by the GitHub Actions workflow.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from .config import STATE_DIR

# Once a story is posted we refuse to post it again for this long.
TTL_SECONDS = 21 * 24 * 3600


class SeenStore:
    def __init__(self, path: Path | None = None):
        self.path = path or (STATE_DIR / "seen.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, float] = {}
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text())
            except (json.JSONDecodeError, OSError):
                self._data = {}
        self._prune()

    def _prune(self) -> None:
        cutoff = time.time() - TTL_SECONDS
        self._data = {k: v for k, v in self._data.items() if v > cutoff}

    def has(self, uid: str) -> bool:
        return uid in self._data

    def add(self, uid: str) -> None:
        self._data[uid] = time.time()

    def add_many(self, uids: list[str]) -> None:
        for u in uids:
            self.add(u)

    def save(self) -> None:
        self._prune()
        self.path.write_text(json.dumps(self._data, indent=0, sort_keys=True))

    def __len__(self) -> int:
        return len(self._data)
