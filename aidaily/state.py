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


# How far back PublishedLog.recent() looks when building the editorial
# gate's "already covered" context. Deliberately shorter than SeenStore's
# TTL_SECONDS (21 days) - SeenStore's job is "never re-post this exact
# article", this one's job is "don't pick a same-theme rehash as today's top
# story", which only matters while the earlier coverage is still recent
# enough that a reader would notice the repeat.
RECENT_WINDOW_DAYS = 14


class PublishedLog:
    """What we actually published recently, by headline - not by article URL.

    SeenStore stops the exact same article from being posted twice, but a
    follow-up piece about the same underlying story (a different URL, a
    different outlet, a "part 2" post) sails right past that check. This
    gives the editorial gate visibility into recent headlines/themes so it
    can recognise "we already covered this" even when the specific article
    is new, and down-rank or reject a same-theme rehash accordingly.
    """

    def __init__(self, path: Path | None = None):
        self.path = path or (STATE_DIR / "published_log.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: list[dict] = []
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text())
            except (json.JSONDecodeError, OSError):
                self._data = []
        self._prune()

    def _prune(self) -> None:
        cutoff = time.time() - RECENT_WINDOW_DAYS * 24 * 3600
        self._data = [e for e in self._data if e.get("ts", 0) > cutoff]

    def add(self, date: str, headline: str, company: str = "", category: str = "") -> None:
        self._data.append({
            "ts": time.time(), "date": date, "headline": headline,
            "company": company, "category": category,
        })

    def recent(self) -> list[dict]:
        """Published entries from the last RECENT_WINDOW_DAYS, oldest first."""
        self._prune()
        return sorted(self._data, key=lambda e: e["ts"])

    def save(self) -> None:
        self._prune()
        self.path.write_text(json.dumps(self._data, indent=0))

    def __len__(self) -> int:
        return len(self._data)
