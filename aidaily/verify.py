"""Stage 2 - the credibility gate.

This is the module that makes the channel trustworthy, so the rules are
deliberately conservative and deliberately explicit. A story only survives if
we can point at *who said it*:

  tier 1  the organisation announcing its own work, a regulator, or a preprint
          venue. Publishable alone - the primary source IS the evidence.
  tier 2  an established newsroom. Publishable only with a second independent
          report, or an outbound link to a tier-1 primary source.
  tier 3  aggregators. Never publishable alone under any circumstances.

Anything that fails is dropped with a recorded reason, so a rejected run can
be audited rather than guessed at.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from functools import lru_cache
from urllib.parse import urlparse

from .models import Item, Story

log = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[a-z0-9]+")

_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "at",
    "by", "from", "is", "are", "was", "were", "be", "been", "it", "its", "as",
    "that", "this", "these", "those", "new", "now", "how", "why", "what",
    "says", "said", "will", "can", "could", "up", "out", "over", "after",
}


def _tokens(text: str) -> set[str]:
    # len >= 2 keeps acronyms that carry the whole meaning of a headline
    # ("EU", "AI", "US"); the stopword list does the real filtering.
    return {
        w for w in _WORD_RE.findall(text.lower())
        if w not in _STOPWORDS and len(w) >= 2
    }


def _similarity(a: str, b: str) -> float:
    """Overlap coefficient on content words. Robust to headline rewrites.

    Overlap rather than plain Jaccard because outlets rewrite headlines at
    very different lengths - "Europe issues first compliance guidance under
    the AI Act" and "EU AI Act enforcement body publishes first compliance
    guidance" are the same event told at different widths.
    """
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def _canon(url: str) -> str:
    """Strip query strings and trailing slashes so links compare equal."""
    if not url:
        return ""
    try:
        p = urlparse(url)
        host = p.netloc.lower()
        host = host[4:] if host.startswith("www.") else host
        return f"{host}{p.path.rstrip('/')}"
    except ValueError:
        return url


def _domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except ValueError:
        return ""


def primary_domains(items: list[Item]) -> set[str]:
    """Domains that count as primary, derived from the tier-1 feeds in use."""
    return {_domain(i.link) for i in items if i.source_tier == 1 and i.link}


def _links_to(a: Item, b: Item) -> bool:
    """True if either item cites the other's article.

    This is a much stronger same-story signal than any headline heuristic:
    when The Verge writes about an Nvidia announcement and links to
    blogs.nvidia.com, those are definitionally one story. Catching this is
    what stops the same event occupying two slides of the carousel.
    """
    ca, cb = _canon(a.link), _canon(b.link)
    if ca and cb and ca == cb:
        return True
    if cb and any(_canon(l) == cb for l in a.outlinks):
        return True
    if ca and any(_canon(l) == ca for l in b.outlinks):
        return True
    return False


def cluster(items: list[Item], threshold: float) -> list[Story]:
    """Greedy single-pass clustering of items describing the same event.

    Two items merge if either the citation graph connects them, or their
    headlines overlap enough. Each item is compared against every member of a
    cluster, not just its seed, so a chain A-B-C collapses correctly.
    """
    stories: list[Story] = []
    # Highest-authority, most recent first, so clusters form around primaries.
    ordered = sorted(items, key=lambda i: (i.source_tier, -i.published.timestamp()))

    for item in ordered:
        placed = False
        for story in stories:
            match = any(
                _links_to(item, existing)
                or _similarity(item.title, existing.title) >= threshold
                for existing in story.items
            )
            if match:
                story.items.append(item)
                placed = True
                break
        if not placed:
            stories.append(Story(items=[item]))

    log.info("clustered %d items into %d stories", len(items), len(stories))
    return stories


def _hedge_penalty(text: str, hedge_terms: list[str]) -> int:
    low = text.lower()
    return sum(1 for term in hedge_terms if term in low)


def _matches(text: str, terms: list[str]) -> str | None:
    low = text.lower()
    for term in terms:
        if term in low:
            return term
    return None


@lru_cache(maxsize=512)
def _term_re(term: str) -> re.Pattern:
    """Compile a category keyword.

    "releas*" -> prefix match, so released / releases / releasing all hit.
    "act"     -> whole word, so "the AI Act" hits but "impact" does not.
    """
    if term.endswith("*"):
        return re.compile(r"\b" + re.escape(term[:-1]), re.I)
    return re.compile(r"\b" + re.escape(term) + r"\b", re.I)


def classify(story: Story, cfg: dict) -> str:
    """Assign an editorial category from the headline and summary.

    Categories drive ranking: a model release outranks a funding round, which
    is the briefed editorial priority. The highest-boost matching category
    wins, so a launch that is also a research paper is filed as a launch.
    """
    text = f"{story.title} {story.lead.summary}"
    boosts = cfg["category_boost"]

    best, best_boost = "research", -1.0
    for category, terms in cfg["category_keywords"].items():
        if any(_term_re(t).search(text) for t in terms):
            boost = boosts.get(category, 0.0)
            if boost > best_boost:
                best, best_boost = category, boost
    return best


def _has_primary_outlink(story: Story, primaries: set[str]) -> bool:
    for item in story.items:
        for link in item.outlinks:
            if _domain(link) in primaries:
                return True
    return False


def verify(stories: list[Story], settings: dict, primaries: set[str]) -> list[Story]:
    """Apply the tier rules. Mutates and returns the same Story objects."""
    cfg = settings["verify"]
    hedges = cfg["hedge_terms"]

    for story in stories:
        story.best_tier = min(i.source_tier for i in story.items)
        story.corroboration = len({i.source_name for i in story.items})
        story.category = classify(story, cfg)
        has_primary_link = _has_primary_outlink(story, primaries)

        # --- hard rejects, applied before anything else --------------------
        # Clickbait disqualifies at any tier: a brief that trades on
        # "you won't believe" is not the brand being built here.
        hit = _matches(story.title, cfg.get("clickbait_terms", []))
        if hit:
            story.verified = False
            story.reject_reason = f"clickbait phrasing ({hit!r})"
            continue

        # Rumour and leak language disqualifies tier-2 and tier-3 only. A
        # company announcing its own product never writes "reportedly", so
        # this cannot suppress a genuine primary announcement.
        if story.best_tier >= 2:
            hit = _matches(f"{story.title} {story.lead.summary}",
                           cfg.get("reject_terms", []))
            if hit:
                story.verified = False
                story.reject_reason = f"unverified/rumour language ({hit!r})"
                continue

        if story.best_tier == 1:
            story.verified = True

        elif story.best_tier == 2:
            if story.corroboration >= cfg["tier2_min_corroboration"]:
                story.verified = True
            elif has_primary_link:
                story.verified = True
            else:
                story.verified = False
                story.reject_reason = (
                    f"single tier-2 report ({story.lead.source_name}) with no primary "
                    f"source link and no corroboration"
                )

        else:  # tier 3
            tiered = [i for i in story.items if i.source_tier <= 2]
            if story.corroboration >= cfg["tier3_min_corroboration"] and tiered:
                story.verified = True
            else:
                story.verified = False
                story.reject_reason = "aggregator-only story, not independently reported"

        # Hedged headlines are never outright rejected (a well-sourced
        # "reportedly" can still be real news) but they are pushed down and
        # blocked from the lead slot by the sort below.
        hedge = _hedge_penalty(story.title, hedges)

        age_h = (
            datetime.now(timezone.utc) - story.lead.published
        ).total_seconds() / 3600.0

        tier_weight = {1: 6.0, 2: 3.5, 3: 1.0}[story.best_tier]
        story.score = (
            tier_weight
            + cfg["category_boost"].get(story.category, 0.0)  # editorial priority
            + 1.6 * (story.corroboration - 1)      # independent confirmation
            + (2.0 if has_primary_link else 0.0)   # points at the source
            + max(0.0, 3.0 - age_h / 8.0)          # freshness
            - 2.5 * hedge                          # speculation penalty
        )

    kept = [s for s in stories if s.verified]
    dropped = [s for s in stories if not s.verified]
    log.info("verify: %d passed, %d rejected", len(kept), len(dropped))
    for s in dropped[:15]:
        log.debug("  rejected %-60s | %s", s.title[:60], s.reject_reason)

    return kept


def select(stories: list[Story], settings: dict, seen) -> list[Story]:
    """Rank, drop anything already covered, and take the top N."""
    cfg = settings["verify"]
    fresh = [s for s in stories if not any(seen.has(i.uid) for i in s.items)]
    ranked = sorted(fresh, key=lambda s: s.score, reverse=True)

    target = cfg["target_story_count"]
    # With only three slides, two stories from one source reads as a single
    # company's press day rather than a brief. One per source at this size.
    cap = 1 if target <= 3 else 2

    picked: list[Story] = []
    per_source: dict[str, int] = {}
    for story in ranked:
        src = story.lead.source_name
        if per_source.get(src, 0) >= cap:
            continue
        picked.append(story)
        per_source[src] = per_source.get(src, 0) + 1
        if len(picked) >= target:
            break

    # If diversity starved us, backfill rather than ship a short carousel.
    if len(picked) < target:
        for story in ranked:
            if story not in picked:
                picked.append(story)
            if len(picked) >= target:
                break

    log.info(
        "selected %d stories: %s", len(picked),
        ", ".join(f"{s.category}/{s.lead.source_name}" for s in picked),
    )
    return picked
