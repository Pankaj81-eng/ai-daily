"""Stage 4a - render the Instagram carousel.

Slides are laid out as HTML and screenshotted with headless Chromium, which
gives real typography, gradients and image compositing without fighting an
imaging library.

Up to 3 stories a day now (see aidaily.editorial), each independently
cleared the bar - so the deck is a fixed 1-cover + N-story + 1-follow shape,
never more than 5 slides even at the 3-story cap:
  1 story:  headline (image-led) -> story (what/why, one line each) -> follow
  2-3:      cover (teases each story) -> one story slide each -> follow

Every "story" slide is deliberately compact: one sentence for what happened,
one for why it matters, no "TechTales Take" - that only existed in the old
fixed 4-slide single-story format and does not fit this leaner shape.

Instagram crops every slide in a carousel to the aspect ratio of the FIRST
slide, so all slides are rendered on an identical 1080x1350 canvas.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image

from .config import ROOT
from .images import detect_company
from .models import Edition, Story

log = logging.getLogger(__name__)

CATEGORY_LABELS = {
    "model_release": "Model release",
    "product_launch": "Product launch",
    "tool_release": "Tool release",
    "regulation": "Regulation",
    "business": "Business",
    "research": "Research",
}


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(ROOT / "templates"),
        autoescape=select_autoescape(["html"]),
    )


def _uri(path: str | Path | None) -> str | None:
    """Absolute file:// URI, or None if the asset is missing."""
    if not path:
        return None
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    return p.resolve().as_uri() if p.exists() else None


def _logo_uri(configured: str | None) -> str | None:
    """Find the brand logo, tolerating whatever format it was exported as.

    Checks the configured path first, then any assets/logo.* sibling, so
    dropping in logo.jpg or logo.webp just works instead of silently falling
    back to the text wordmark.
    """
    found = _uri(configured)
    if found:
        return found
    if not configured:
        return None

    p = Path(configured)
    folder = (ROOT / p).parent if not p.is_absolute() else p.parent
    for ext in ("png", "jpg", "jpeg", "webp", "svg"):
        candidate = folder / f"{p.stem}.{ext}"
        if candidate.exists():
            log.info("using %s as the brand logo", candidate.name)
            return candidate.resolve().as_uri()

    log.warning(
        "no logo found at %s - slides will use the text wordmark. Drop a "
        "square PNG there to brand them.", configured,
    )
    return None


def _headline_size(text: str) -> int:
    """Scale the headline so long and short ones both fill the block.

    Headlines are capped at 12 words upstream, but word length still varies a
    lot ("Meta ships Llama" vs "European regulators publish enforcement
    guidance"). Fixed type would either overflow or look lost.
    """
    n = len(text)
    if n <= 34:
        return 66
    if n <= 48:
        return 60
    if n <= 64:
        return 54
    return 48


def _card_size(bullets: list[str]) -> int:
    """Type size for the text-only 'story' slide's what/why cards - these
    have the whole slide to themselves (no image eating half the canvas),
    so they can run noticeably bigger than the image-led headline slide's
    copy."""
    total = sum(len(b) for b in bullets)
    if total <= 90:
        return 42
    if total <= 150:
        return 36
    if total <= 220:
        return 31
    return 27


# Shrinks a slide's copy until it fits its fixed area. Each slide kind has
# its own box/inner pair (.copy/.copy-inner for the headline slide,
# .wim/.wim-inner for the story slide, .cover-body/.cover-inner for the
# multi-story cover) - try each rather than hard-coding one, since which
# pair exists depends on which slide is on screen. The follow slide has no
# pair here - its copy is fixed, known-short text, not model-generated.
_AUTOFIT_JS = """
() => {
  const pairs = [['.copy', '.copy-inner'], ['.wim', '.wim-inner'],
                 ['.cover-body', '.cover-inner']];
  let box = null, inner = null;
  for (const [b, i] of pairs) {
    const bEl = document.querySelector(b), iEl = document.querySelector(i);
    if (bEl && iEl) { box = bEl; inner = iEl; break; }
  }
  if (!box || !inner) return 1;
  let fit = 1;
  const root = document.documentElement;
  // Safety margin so the last card/line never sits flush against the footer rule.
  const limit = box.clientHeight - 16;
  while (inner.scrollHeight > limit && fit > 0.70) {
    fit = Math.round((fit - 0.03) * 100) / 100;
    root.style.setProperty('--fit', String(fit));
  }
  return fit;
}
"""


def _subject_for(story: Story, category_label: str) -> str:
    """The company the story is ABOUT, never the outlet or repository that
    reported it - a research-repository feed like arXiv (which has no
    per-article identity of its own) must never end up rendered as if it
    were the subject. story.company is only populated here if the image
    stage already detected one (it skips detection once an official image
    is found, so this re-runs it rather than trusting story.company is
    reliably set); if no company can be identified at all, fall back to the
    editorial category - never to the source name.
    """
    return story.company or (detect_company(story) or (None, None))[0] or category_label


def _slide_specs(edition: Edition, settings: dict) -> list[dict]:
    """Build one spec dict per slide: 1 cover/headline + 1 per story + 1
    follow. Slide count adapts to story count (always 1-3, enforced by
    aidaily.editorial): 3 slides for 1 story, 4 for 2, 5 for 3. Never more
    than 5 - Instagram's 10-slide carousel cap is nowhere close to binding
    at this size, but the point is to stay short regardless.
    """
    brand = settings["brand"]
    ccfg = settings["carousel"]
    stories = edition.stories
    n = len(stories)
    total = n + 2

    date_label = datetime.strptime(edition.date, "%Y-%m-%d").strftime("%d %b %Y")

    common = {
        "w": ccfg["width"],
        "h": ccfg["height"],
        "img_h": int(ccfg["height"] * ccfg["image_ratio"]),
        "c": brand,
        "brand_name": brand["name"],
        "tagline": brand["tagline"],
        "handle": brand["handle"],
        "youtube": brand["youtube"],
        "date_label": date_label,
        "logo_uri": _logo_uri(brand.get("logo")),
        "pages": total,
    }

    specs: list[dict] = []
    page = 1

    if n == 1:
        # Single story: slide 1 is the familiar image-led headline slide,
        # unchanged from the one-story format.
        story = stories[0]
        category_label = CATEGORY_LABELS.get(story.category, "AI news")
        specs.append({
            **common,
            "kind": "headline",
            "title": story.headline,
            "image_uri": _uri(story.image_path),
            "headline_size": _headline_size(story.headline),
            "source": story.source_label,
            "subject": _subject_for(story, category_label),
            "category_label": category_label,
            "page": page,
        })
        page += 1
    else:
        # Multiple stories: slide 1 is a text-only cover teasing each one -
        # no single image represents N stories, so this doesn't try.
        specs.append({
            **common,
            "kind": "cover",
            "teasers": [s.teaser or s.headline for s in stories],
            "page": page,
        })
        page += 1

    for story_idx, story in enumerate(stories):
        category_label = CATEGORY_LABELS.get(story.category, "AI news")
        what = story.bullets[0] if story.bullets else ""
        why = story.why_bullets[0] if story.why_bullets else ""
        specs.append({
            **common,
            "kind": "story",
            "story_headline": story.headline,
            "what": what,
            "why": why,
            "story_size": _card_size([what, why]),
            "source": story.source_label,
            "subject": _subject_for(story, category_label),
            "story_label": f"Story {story_idx + 1} of {n}" if n > 1 else None,
            "page": page,
        })
        page += 1

    specs.append({**common, "kind": "follow", "page": page})

    return specs


def render(edition: Edition, settings: dict, out_dir: Path) -> list[Path]:
    """Render all slides to PNG. Returns paths in carousel order."""
    from playwright.sync_api import sync_playwright

    # Chromium is handed file:// URIs, which require absolute paths - a
    # relative --out would otherwise crash on Path.as_uri().
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    tpl = _env().get_template("slide.html.j2")
    specs = _slide_specs(edition, settings)

    w, h = settings["carousel"]["width"], settings["carousel"]["height"]
    paths: list[Path] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--font-render-hinting=none",
                                           "--allow-file-access-from-files"])
        page = browser.new_page(viewport={"width": w, "height": h},
                                device_scale_factor=1)

        for i, spec in enumerate(specs):
            html_path = out_dir / f"slide_{i:02d}.html"
            html_path.write_text(tpl.render(**spec), encoding="utf-8")
            page.goto(html_path.as_uri())
            page.wait_for_timeout(750)          # let webfonts and images settle

            # Every slide now carries a .copy/.copy-inner autofit box (the
            # headline slide included), since a single story's copy can run
            # long in ways a fixed 3-bullet-max deck never had to absorb.
            fit = page.evaluate(_AUTOFIT_JS)
            if fit < 1.0:
                page.wait_for_timeout(120)

            png = out_dir / f"slide_{i:02d}.png"
            page.screenshot(path=str(png))

            # Instagram's Content Publishing API accepts JPEG only - "JPEG is
            # the only image format supported". PNGs are kept alongside for
            # previews and archiving; the JPEGs are what get published.
            jpg = out_dir / f"slide_{i:02d}.jpg"
            with Image.open(png) as im:
                im.convert("RGB").save(jpg, "JPEG", quality=92, optimize=True)

            paths.append(jpg)
            log.info(
                "rendered %s (%s)%s", jpg.name, spec["kind"],
                "" if fit == 1.0 else f"  [auto-fit {fit:.2f}]",
            )

        browser.close()

    return paths
