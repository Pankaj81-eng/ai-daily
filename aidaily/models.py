"""Core data structures passed between pipeline stages."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any


@dataclass
class Source:
    """A single feed we are allowed to read from."""

    name: str
    url: str
    tier: int
    tags: list[str] = field(default_factory=list)


@dataclass
class Item:
    """One article as it came off a feed, before any clustering."""

    title: str
    link: str
    summary: str
    published: datetime
    source_name: str
    source_tier: int
    tags: list[str] = field(default_factory=list)
    # Outbound links found in the article body, used to detect when a press
    # story is pointing at a primary announcement.
    outlinks: list[str] = field(default_factory=list)

    @property
    def uid(self) -> str:
        """Stable id for the dedupe store. Canonical link, else title."""
        basis = (self.link or self.title).strip().lower()
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


@dataclass
class Story:
    """A cluster of Items that all describe the same event."""

    items: list[Item]
    # Filled in by verify.py
    best_tier: int = 9
    corroboration: int = 0
    verified: bool = False
    reject_reason: str | None = None
    score: float = 0.0
    # Editorial category, used to rank launches above commentary.
    category: str = "research"

    # Filled in by summarize.py
    headline: str = ""
    # 3-5 word hook shown on the cover slide. Deliberately shorter than the
    # headline: the cover sells the swipe, it is not a table of contents.
    teaser: str = ""
    bullets: list[str] = field(default_factory=list)     # "What happened" (max 3)
    body: str = ""            # bullets joined, for the video frame
    why_it_matters: str = ""  # legacy single-line takeaway, kept for make_edition.py
    # "Why engineers should care" (max 3) - the editorial-gate slide format.
    why_bullets: list[str] = field(default_factory=list)
    # "TechTales Take" - one original insight or prediction. Must not repeat
    # the news; this is the editor's judgment on what it implies.
    take: str = ""
    # Spoken narration for this story's frame in the short. Kept per-story so
    # audio and visuals stay aligned without re-splitting a monolithic script.
    script_line: str = ""

    # Filled in by images.py
    image_path: str | None = None
    image_kind: str = "generated"   # official | product | logo | generated
    image_credit: str = ""
    # The company the story is ABOUT, which is not the publisher reporting it.
    company: str = ""

    @property
    def source_label(self) -> str:
        """Short attribution shown on the slide, e.g. 'OpenAI' or 'TechCrunch'."""
        name = self.lead.source_name
        for suffix in (" Blog", " News", " AI", " Research Blog", " (AI front page)"):
            if name.endswith(suffix):
                name = name[: -len(suffix)]
        return name.strip() or self.lead.source_name

    @property
    def lead(self) -> Item:
        """The most authoritative item in the cluster; what we cite."""
        return min(self.items, key=lambda i: (i.source_tier, -i.published.timestamp()))

    @property
    def title(self) -> str:
        return self.lead.title

    @property
    def link(self) -> str:
        return self.lead.link

    @property
    def sources(self) -> list[str]:
        seen, out = set(), []
        for i in sorted(self.items, key=lambda x: x.source_tier):
            if i.source_name not in seen:
                seen.add(i.source_name)
                out.append(i.source_name)
        return out

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["items"] = [
            {**asdict(i), "published": i.published.isoformat()} for i in self.items
        ]
        d["headline"] = self.headline
        d["link"] = self.link
        d["sources"] = self.sources
        return d


@dataclass
class Edition:
    """Everything one morning's run produces."""

    date: str
    stories: list[Story]
    intro: str = ""           # on-screen cover title
    outro: str = ""
    intro_line: str = ""      # spoken opening of the short
    caption: str = ""         # Instagram caption
    # Slide 5 - one sentence each, in this order.
    matters_professionals: str = ""
    matters_businesses: str = ""
    matters_learners: str = ""
    yt_title: str = ""
    yt_description: str = ""

    @property
    def script(self) -> str:
        """Full narration, for reference and for the YouTube description."""
        return " ".join(
            [self.intro_line] + [s.script_line for s in self.stories]
        ).strip()

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "intro": self.intro,
            "outro": self.outro,
            "intro_line": self.intro_line,
            "script": self.script,
            "caption": self.caption,
            "yt_title": self.yt_title,
            "yt_description": self.yt_description,
            "stories": [s.to_dict() for s in self.stories],
        }
