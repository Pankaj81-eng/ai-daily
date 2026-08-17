"""Stage 4a - render the four-slide Instagram carousel.

Slides are laid out as HTML and screenshotted with headless Chromium, which
gives real typography, gradients and image compositing without fighting an
imaging library.

One story a day now, not three (see aidaily.editorial) - so the carousel is a
fixed four slides, not a variable cover+N+matters+follow deck:
  1  headline    image-led, the headline, source
  2  what        what happened - up to three bullets, no image (more room)
  3  why         why engineers should care - up to three bullets
  4  take        the TechTales Take + follow CTA folded into the footer

Instagram crops every slide in a carousel to the aspect ratio of the FIRST
slide, so all four are rendered on an identical 1080x1350 canvas.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image

from .config import ROOT
from .images import detect_company
from .models import Edition

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


def _bullet_size(bullets: list[str]) -> int:
    total = sum(len(b) for b in bullets)
    if total <= 130:
        return 32
    if total <= 200:
        return 29
    return 26


def _why_size(text: str) -> int:
    return 30 if len(text) <= 78 else 27


def _card_size(bullets: list[str]) -> int:
    """Type size for the text-only 'what'/'why' slides - these have the
    whole slide to themselves (no image eating half the canvas), so they can
    run noticeably bigger than the image-led headline slide's bullets."""
    total = sum(len(b) for b in bullets)
    if total <= 90:
        return 42
    if total <= 150:
        return 36
    if total <= 220:
        return 31
    return 27


def _take_size(text: str) -> int:
    if len(text) <= 110:
        return 46
    if len(text) <= 180:
        return 40
    return 34


# Shrinks a slide's copy until it fits its fixed area. Each slide kind has
# its own box/inner pair (.copy/.copy-inner for the headline slide,
# .wim/.wim-inner for what/why, .take-wrap/.take-inner for the take slide) -
# try each rather than hard-coding one, since which pair exists depends on
# which slide is on screen.
_AUTOFIT_JS = """
() => {
  const pairs = [['.copy', '.copy-inner'], ['.wim', '.wim-inner'],
                 ['.take-wrap', '.take-inner']];
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


def _slide_specs(edition: Edition, settings: dict) -> list[dict]:
    brand = settings["brand"]
    ccfg = settings["carousel"]
    total = 4

    if len(edition.stories) != 1:
        log.warning(
            "edition has %d stories, but the carousel is now a fixed 4-slide "
            "single-story deck - using the first and ignoring the rest",
            len(edition.stories),
        )
    story = edition.stories[0]

    date_label = datetime.strptime(edition.date, "%Y-%m-%d").strftime("%d %b %Y")
    category_label = CATEGORY_LABELS.get(story.category, "AI news")

    # The generated panel and slide footers name the company the story is
    # ABOUT, never the outlet or repository that reported it - "subject" and
    # "source" must never be interchangeable, or a research-repository feed
    # like arXiv (which has no per-article identity of its own) ends up
    # rendered as if it were the headline. story.company is only populated
    # here if the image stage already detected one (it skips detection once
    # an official image is found, so this re-runs it rather than trusting
    # that story.company is reliably set); if no company can be identified at
    # all, fall back to the editorial category - never to the source name.
    subject = story.company or (detect_company(story) or (None, None))[0] or category_label

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
        "source": story.source_label,
        "subject": subject,
        "category_label": category_label,
    }

    return [
        {
            **common,
            "kind": "headline",
            "title": story.headline,
            "image_uri": _uri(story.image_path),
            "headline_size": _headline_size(story.headline),
            "page": 1,
        },
        {
            **common,
            "kind": "what",
            "card_title": "What happened",
            "bullets": story.bullets,
            "card_size": _card_size(story.bullets),
            "page": 2,
        },
        {
            **common,
            "kind": "why",
            "card_title": "Why engineers should care",
            "bullets": story.why_bullets,
            "card_size": _card_size(story.why_bullets),
            "page": 3,
        },
        {
            **common,
            "kind": "take",
            "take": story.take,
            "take_size": _take_size(story.take),
            "page": 4,
        },
    ]


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
