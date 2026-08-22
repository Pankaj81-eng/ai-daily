"""Stage 2c - enrich thin RSS summaries with real article text before scoring.

Found 22 Aug 2026: the editorial gate rejected a genuinely major-lab story
(Mistral's "Agentic Search" launch) for "thin source text - no performance
numbers, architecture detail, or availability specifics". A live check of
the actual RSS feed confirmed the gate was right about what it was given -
the summary was 119 characters, a single marketing tagline with zero facts:

    "The retrieval layer that helps AI systems navigate, read, and verify
    information inside even the most complex documents"

But the real article at that URL almost certainly has the numbers and
details a launch announcement normally carries - we just never looked at
it. Some sources' RSS feeds only ever carry a tagline-length excerpt, not
the article body, so the editorial LLM was judging genuinely significant
stories on less information than actually exists.

This module closes that gap *narrowly*: only candidates whose RSS summary
is below THIN_SUMMARY_CHARS get a live fetch of the article page, and only
the fetched text (an excerpt, not the whole page) replaces the RSS summary
in what the editorial LLM sees. Most candidates already have a substantial
summary and are left untouched - this is not a blanket re-fetch of every
candidate every day, just a targeted fix for the specific case that caused
a real rejection.
"""

from __future__ import annotations

import logging
import re

import requests
from bs4 import BeautifulSoup

from .models import Story

log = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Mistral's real rejected-story summary was 119 chars. 250 gives real
# multi-sentence summaries (which are common and already plenty for
# scoring) headroom to pass through untouched, while still catching
# tagline-only summaries like this one.
THIN_SUMMARY_CHARS = 250

# An excerpt, not the whole article - enough for the LLM to find concrete
# facts (numbers, availability, what actually shipped) without ballooning
# the prompt across up to 40 candidates.
MAX_EXCERPT_CHARS = 1200

# A paragraph shorter than this is almost always nav/footer/byline chrome,
# not article body - skip it rather than let it dilute the excerpt.
_MIN_PARAGRAPH_CHARS = 40


def fetch_article_excerpt(url: str, timeout_s: int) -> str | None:
    """Best-effort plain-text excerpt of an article page, or None on failure.

    Never raises - a fetch failure here should fall back to the original
    RSS summary, not break the run. Same UA/timeout pattern as images.py's
    article fetch, since it is exactly the same kind of best-effort network
    call against sources we don't control.
    """
    try:
        resp = requests.get(url, timeout=timeout_s, headers={"User-Agent": UA})
        resp.raise_for_status()
    except requests.RequestException as e:
        log.warning("enrich: could not fetch %s (%s)", url, e)
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
    # Repeated nav/footer boilerplate (seen for real on mistral.ai, which
    # renders the same site-nav paragraph twice on the page) would otherwise
    # burn excerpt budget that should go to the article's actual facts -
    # keep each distinct paragraph only once, in first-seen order.
    seen: set[str] = set()
    kept = []
    for p in paragraphs:
        if len(p) >= _MIN_PARAGRAPH_CHARS and p not in seen:
            seen.add(p)
            kept.append(p)
    text = re.sub(r"\s+", " ", " ".join(kept)).strip()
    if not text:
        return None
    return text[:MAX_EXCERPT_CHARS]


def enrich_thin_candidates(
    candidates: list[Story], settings: dict,
) -> dict[int, str]:
    """{candidate index: fetched excerpt} for candidates whose RSS summary
    is too thin to score confidently. Only touches the thin ones; every
    other candidate is scored on its original RSS summary as before.
    """
    timeout_s = settings.get("images", {}).get("request_timeout_s", 20)
    enriched: dict[int, str] = {}
    for i, story in enumerate(candidates):
        summary = story.lead.summary or ""
        if len(summary) >= THIN_SUMMARY_CHARS:
            continue
        excerpt = fetch_article_excerpt(story.link, timeout_s)
        if excerpt and len(excerpt) > len(summary):
            enriched[i] = excerpt
            log.info(
                "enrich: candidate %d summary was thin (%d chars) - "
                "fetched %d chars from the article instead",
                i, len(summary), len(excerpt),
            )
    return enriched
