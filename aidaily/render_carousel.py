"""Stage 4a - render the six-slide Instagram carousel.

Slides are laid out as HTML and screenshotted with headless Chromium, which
gives real typography, gradients and image compositing without fighting an
imaging library.

Structure:
  1     cover           "Today in AI" + the three headlines
  2-4   story           image-led, headline, up to three bullets, source
  5     matters         what today means for builders, businesses, learners
  6     follow          the call to action

Instagram crops every slide in a carousel to the aspect ratio of the FIRST
slide, so all six are rendered on an identical 1080x1350 canvas.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image

from .config import ROOT
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


# Shrinks the story copy until it fits its fixed area. The image panel keeps
# its size; only the type scales, and only when it has to.
_AUTOFIT_JS = """
() => {
  const box = document.querySelector('.copy');
  const inner = document.querySelector('.copy-inner');
  if (!box || !inner) return 1;
  let fit = 1;
  const root = document.documentElement;
  // Safety margin so the "why it matters" card never sits flush against the
  // footer rule.
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
    n_stories = len(edition.stories)
    total = n_stories + 3          # cover + stories + matters + follow

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
        "story_total": n_stories,
    }

    specs = [{
        **common,
        "kind": "cover",
        "subtitle": edition.outro or f"{n_stories} AI stories that matter today",
        # Teasers, not headlines: the cover is a hook, not a contents page.
        "toc": [s.teaser or s.headline for s in edition.stories],
        "page": 1,
    }]

    for i, story in enumerate(edition.stories, start=1):
        specs.append({
            **common,
            "kind": "story",
            "index": i,
            "title": story.headline,
            "bullets": story.bullets,
            "why": story.why_it_matters,
            "source": story.source_label,
            # The generated panel names the company the story is about, which
            # is more recognisable than the outlet that reported it.
            "subject": story.company or story.source_label,
            "category_label": CATEGORY_LABELS.get(story.category, "AI news"),
            "image_uri": _uri(story.image_path),
            "headline_size": _headline_size(story.headline),
            "bullet_size": _bullet_size(story.bullets),
            "why_size": _why_size(story.why_it_matters),
            "page": i + 1,
        })

    specs.append({
        **common,
        "kind": "matters",
        "professionals": edition.matters_professionals,
        "businesses": edition.matters_businesses,
        "learners": edition.matters_learners,
        "page": total - 1,
    })

    specs.append({**common, "kind": "follow", "page": total})
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

            fit = 1.0
            if spec["kind"] == "story":
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
