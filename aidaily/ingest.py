"""Stage 1 - pull candidate stories from the allowlisted feeds.

Nothing here decides what is true; it only decides what is *recent*, *on
topic*, and *from a source we have vetted*. Truth filtering happens in
verify.py.
"""

from __future__ import annotations

import concurrent.futures
import logging
import re
from datetime import datetime, timedelta, timezone

import feedparser
import requests
from bs4 import BeautifulSoup

from .models import Item, Source

log = logging.getLogger(__name__)

UA = "Mozilla/5.0 (compatible; AIDailyBot/1.0; +https://github.com/)"
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    if not text:
        return ""
    txt = BeautifulSoup(text, "html.parser").get_text(" ")
    return re.sub(r"\s+", " ", txt).strip()


def _extract_links(html: str) -> list[str]:
    """Outbound links in an article summary.

    Used by verify.py: a press story that links to openai.com/blog is
    self-corroborating in a way one that links nowhere is not.
    """
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    return [a["href"] for a in soup.find_all("a", href=True)][:40]


def _parse_date(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        val = getattr(entry, key, None) or entry.get(key)
        if val:
            try:
                return datetime(*val[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    return None


def _is_on_topic(text: str, keywords: list[str]) -> bool:
    low = text.lower()
    return any(k in low for k in keywords)


def fetch_source(src: Source, settings: dict) -> list[Item]:
    """Fetch and normalise one feed. Never raises - a dead feed yields []."""
    cfg = settings["ingest"]
    cutoff = datetime.now(timezone.utc) - timedelta(hours=cfg["lookback_hours"])
    items: list[Item] = []

    try:
        resp = requests.get(
            src.url, timeout=cfg["request_timeout_s"], headers={"User-Agent": UA}
        )
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
    except Exception as exc:  # noqa: BLE001 - a broken feed must not kill the run
        log.warning("source %s failed: %s", src.name, exc)
        return []

    for entry in parsed.entries[: cfg["max_items_per_source"]]:
        published = _parse_date(entry)
        if published is None or published < cutoff:
            continue

        title = _strip_html(entry.get("title", ""))
        raw_summary = entry.get("summary", "") or entry.get("description", "")
        summary = _strip_html(raw_summary)
        if not title:
            continue

        # Lab and research feeds are inherently on topic; press feeds are not.
        needs_topic_check = "press" in src.tags or "wire" in src.tags or "aggregator" in src.tags
        if needs_topic_check and not _is_on_topic(
            f"{title} {summary}", cfg["topic_keywords"]
        ):
            continue

        items.append(
            Item(
                title=title,
                link=entry.get("link", ""),
                summary=summary[:1200],
                published=published,
                source_name=src.name,
                source_tier=src.tier,
                tags=src.tags,
                outlinks=_extract_links(raw_summary),
            )
        )

    log.info("source %-24s -> %d items", src.name, len(items))
    return items


def fetch_all(sources: list[Source], settings: dict) -> list[Item]:
    """Fetch every source in parallel and return one flat, deduped list."""
    out: list[Item] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(fetch_source, s, settings): s for s in sources}
        for fut in concurrent.futures.as_completed(futures):
            out.extend(fut.result())

    # Exact-URL dedupe; near-duplicate clustering happens in verify.py.
    by_uid: dict[str, Item] = {}
    for item in out:
        prev = by_uid.get(item.uid)
        if prev is None or item.source_tier < prev.source_tier:
            by_uid[item.uid] = item

    items = sorted(by_uid.values(), key=lambda i: i.published, reverse=True)
    log.info("ingested %d unique items from %d sources", len(items), len(sources))
    return items
