#!/usr/bin/env python3
"""Render a carousel from hand-written copy instead of the live pipeline.

    python make_edition.py editions/2026-08-14.json

Useful for two things:
  * reviewing or fixing a day's copy before it goes out, without re-running
    ingestion
  * producing an edition when you want full editorial control

The JSON mirrors what the pipeline produces in out/<date>/edition.json, so you
can copy that file, edit the wording, and re-render.

Schema:
{
  "date": "2026-08-14",
  "cover_subtitle": "3 AI stories that matter today",
  "intro_line": "spoken opening for the video",
  "matters_professionals": "...",
  "matters_businesses": "...",
  "matters_learners": "...",
  "caption": "...",
  "yt_title": "...",
  "yt_description": "...",
  "stories": [
    {"headline": "...", "teaser": "...", "bullets": ["...", "..."],
     "source": "OpenAI", "company": "OpenAI", "link": "https://...",
     "tier": 1, "category": "product_launch", "script_line": "...",
     "image": "optional/path/to/image.jpg"}
  ]
}
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aidaily import images, render_carousel, render_video          # noqa: E402
from aidaily.config import OUT_DIR, load_settings                  # noqa: E402
from aidaily.models import Edition, Item, Story                    # noqa: E402

log = logging.getLogger("make_edition")


def build_edition(data: dict, settings: dict) -> Edition:
    stories: list[Story] = []
    for s in data["stories"]:
        item = Item(
            title=s.get("original_title", s["headline"]),
            link=s.get("link", ""),
            summary=s.get("summary", ""),
            published=datetime.now(timezone.utc),
            source_name=s.get("source", ""),
            source_tier=int(s.get("tier", 2)),
        )
        story = Story(items=[item])
        story.best_tier = item.source_tier
        story.corroboration = int(s.get("corroboration", 1))
        story.verified = True
        story.category = s.get("category", "research")
        story.headline = s["headline"]
        story.teaser = s.get("teaser", "")
        story.bullets = list(s.get("bullets", []))
        story.why_it_matters = s.get("why_it_matters", "")
        story.body = " ".join(story.bullets)
        story.script_line = s.get("script_line", f"{story.headline}. {story.body}")
        story.company = s.get("company", "")
        if s.get("image"):
            story.image_path = s["image"]
            story.image_kind = "official"
        stories.append(story)

    return Edition(
        date=data["date"],
        stories=stories,
        intro="Today in AI",
        outro=data.get("cover_subtitle", f"{len(stories)} AI stories that matter today"),
        intro_line=data.get("intro_line", ""),
        matters_professionals=data.get("matters_professionals", ""),
        matters_businesses=data.get("matters_businesses", ""),
        matters_learners=data.get("matters_learners", ""),
        caption=data.get("caption", ""),
        yt_title=data.get("yt_title", ""),
        yt_description=data.get("yt_description", ""),
    )


def main(path: Path, out_dir: Path | None = None, video: bool | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
    settings = load_settings()
    data = json.loads(path.read_text())

    out = out_dir or (OUT_DIR / data["date"])
    out.mkdir(parents=True, exist_ok=True)

    edition = build_edition(data, settings)

    # Fetch imagery for any story that did not supply its own.
    missing = [s for s in edition.stories if not s.image_path]
    if missing and settings["images"].get("enabled", True):
        try:
            images.attach_images(missing, settings, out)
        except Exception as exc:  # noqa: BLE001 - offline is fine, panels cover it
            log.warning("image lookup failed (%s); using branded panels", exc)

    (out / "edition.json").write_text(json.dumps(edition.to_dict(), indent=2))
    slides = render_carousel.render(edition, settings, out)
    log.info("rendered %d slides into %s", len(slides), out)

    want_video = settings["video"].get("enabled", True) if video is None else video
    if want_video:
        try:
            render_video.render(edition, settings, out)
        except Exception as exc:  # noqa: BLE001
            log.error("video render failed, carousel is unaffected: %s", exc)

    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    args = sys.argv[1:]
    no_video = "--no-video" in args
    args = [a for a in args if not a.startswith("--")]
    raise SystemExit(main(Path(args[0]), video=False if no_video else None))
