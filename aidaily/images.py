"""Stage 3b - find the large visual that carries each story slide.

The carousel is image-led, so this module decides what people actually look
at. Strategy, in order:

  1. The article's own Open Graph image. This is the picture the publisher
     explicitly nominated for sharing - the official product shot, the
     announcement hero, the chip render. Highest fidelity and clearly the
     intended-for-redistribution asset.
  2. The company's logo, pulled from the source domain, centred on a branded
     panel. Consistent and always available.
  3. Nothing - the template then renders a generated branded panel with the
     company wordmark, so a slide is never broken.

Every image is composited onto a blurred copy of itself so that any aspect
ratio fills the panel cleanly. Hard-cropping a 1.91:1 press image into a
1.14:1 panel throws away the sides, which is usually where the product is.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageEnhance, ImageFilter

from .models import Story

log = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Junk that shows up in og:image slots on some sites.
_BAD_IMAGE_HINTS = (
    "placeholder", "default-", "fallback", "sprite", "1x1", "pixel",
    "blank.", "avatar", "gravatar", "logo-white", "spacer",
)


# Sites that serve one static, site-wide image for every single page (a
# repository's logo, not per-item art). An "official image" lookup on these
# always returns the same generic picture for every story - arXiv abstract
# pages all share the exact same og:image (arxiv-logo-fb.png). This is
# supposed to be caught by is_generic_share_card(), but that only works by
# comparing against the *homepage's* og:image - and arxiv.org's homepage sets
# no og:image at all, so the generic logo slips through undetected. Skip
# these domains outright rather than relying on a check that can't see them.
#
# aws.amazon.com/blogs/machine-learning was deliberately NOT added here,
# despite a real, confirmed issue: its per-article og:image is a templated
# card that bakes in a non-clickable "Read the blog post >" prompt (fixed
# layout, only the headline text differs between articles). Blocking it was
# tried and reverted - the only fallback available (a generic company
# hero/logo image, unrelated to the specific story) was judged worse than
# keeping the templated card. A safe fix would need to detect where the
# headline text ends per-image (it varies with headline length) before
# cropping the CTA out, which needs OCR/vision, not a fixed pixel offset -
# revisit if that becomes worth the added cost/complexity.
_NO_ARTICLE_IMAGE_DOMAINS = {"arxiv.org"}


def _domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except ValueError:
        return ""


def _looks_junk(url: str) -> bool:
    low = url.lower()
    return any(h in low for h in _BAD_IMAGE_HINTS)


# --------------------------------------------------------------------------
# discovery
# --------------------------------------------------------------------------

def _srcset_largest(value: str) -> str | None:
    """Pick the highest-resolution entry from a srcset attribute."""
    best, best_w = None, 0
    for part in value.split(","):
        bits = part.strip().split()
        if not bits:
            continue
        url = bits[0]
        width = 0
        if len(bits) > 1 and bits[1].endswith("w"):
            try:
                width = int(bits[1][:-1])
            except ValueError:
                width = 0
        if width >= best_w:
            best, best_w = url, width
    return best


def find_article_images(page_url: str, timeout: int, limit: int = 6) -> list[str]:
    """Ordered candidate images for an article, best first.

    Returns a list rather than one URL because the first candidate often
    fails - a hotlink block, a redirect to a login wall, a 404 on an expired
    CDN path. Trying several is the difference between a real photo and
    falling through to a logo panel.

    Order: the publisher's nominated share image, then the article's own hero
    and in-body images by size.
    """
    try:
        resp = requests.get(
            page_url, timeout=timeout,
            headers={"User-Agent": UA, "Accept": "text/html,*/*"},
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.debug("could not fetch %s: %s", page_url, exc)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    out: list[str] = []

    def add(raw: str | None) -> None:
        if not raw:
            return
        url = urljoin(page_url, raw.strip())
        if not _looks_junk(url) and url not in out:
            out.append(url)

    # 1. Explicitly nominated share images, most deliberate first.
    for tag, attrs, key in [
        ("meta", {"property": "og:image:secure_url"}, "content"),
        ("meta", {"property": "og:image"}, "content"),
        ("meta", {"name": "og:image"}, "content"),
        ("meta", {"name": "twitter:image"}, "content"),
        ("meta", {"name": "twitter:image:src"}, "content"),
        ("link", {"rel": "image_src"}, "href"),
    ]:
        for el in soup.find_all(tag, attrs=attrs):
            add(el.get(key))

    # 2. The article's own hero and body images, largest first. Scoped to
    #    <article>/<main> where possible so navigation and footer art is
    #    excluded.
    scope = soup.find("article") or soup.find("main") or soup
    sized: list[tuple[int, str]] = []
    for img in scope.find_all("img"):
        src = (
            img.get("src")
            or img.get("data-src")
            or (_srcset_largest(img["srcset"]) if img.get("srcset") else None)
        )
        if not src or _looks_junk(src):
            continue
        try:
            area = int(img.get("width", 0)) * int(img.get("height", 0))
        except (TypeError, ValueError):
            area = 0
        sized.append((area, src))

    # Undeclared dimensions sort last but are still tried; many CMSes omit them.
    for _, src in sorted(sized, key=lambda p: p[0], reverse=True):
        add(src)

    return out[:limit]


@lru_cache(maxsize=64)
def _site_default_image(domain: str, timeout: int) -> str | None:
    """The og:image a site serves on its homepage.

    Many publishers fall back to one house share-card for every article. That
    card is technically an og:image but tells a reader nothing about the
    story, so it is worth detecting and rejecting in favour of the company
    logo panel.
    """
    try:
        resp = requests.get(
            f"https://{domain}/", timeout=timeout, headers={"User-Agent": UA}
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        el = soup.find("meta", attrs={"property": "og:image"})
        return el["content"].strip() if el and el.get("content") else None
    except requests.RequestException:
        return None


def is_generic_share_card(image_url: str, page_url: str, timeout: int) -> bool:
    """True if this image is the site's house card rather than the story's."""
    dom = _domain(page_url)
    if not dom:
        return False
    default = _site_default_image(dom, timeout)
    if not default:
        return False
    same = image_url.split("?")[0].rstrip("/") == default.split("?")[0].rstrip("/")
    if same:
        log.info("rejecting generic site-wide share card from %s", dom)
    return same


@lru_cache(maxsize=1)
def _companies() -> list[tuple[re.Pattern, str, str]]:
    """Compiled alias patterns, longest alias first."""
    from .config import load_companies

    entries: list[tuple[str, str, str]] = []
    for c in load_companies():
        for alias in c.get("aliases", []):
            entries.append((alias, c["name"], c["domain"]))
    entries.sort(key=lambda e: len(e[0]), reverse=True)
    return [
        (re.compile(rf"(?<!\w){re.escape(a)}(?!\w)", re.I), name, dom)
        for a, name, dom in entries
    ]


def _domain_for(company_name: str) -> str | None:
    """Brand domain for a company named explicitly rather than detected."""
    for pattern, name, dom in _companies():
        if name.lower() == company_name.lower() or pattern.fullmatch(company_name):
            return dom
    return None


def detect_company(story: Story) -> tuple[str, str] | None:
    """Which company is this story ABOUT? Returns (name, domain).

    The publisher is not the subject: an article on TechCrunch about Nvidia
    should show Nvidia's imagery, not TechCrunch's. Matching runs over the
    headline first, then the summary, so the subject of the sentence wins over
    a company mentioned in passing.
    """
    haystacks = [story.title, story.headline, story.lead.summary]
    for text in haystacks:
        if not text:
            continue
        for pattern, name, dom in _companies():
            if pattern.search(text):
                return name, dom
    return None


def find_brand_image(domain: str, timeout: int) -> str | None:
    """The company's own hero image - usually the current product shot."""
    try:
        resp = requests.get(
            f"https://{domain}/", timeout=timeout, headers={"User-Agent": UA}
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        el = soup.find("meta", attrs={"property": "og:image"})
        if el and el.get("content"):
            url = urljoin(f"https://{domain}/", el["content"].strip())
            if not _looks_junk(url):
                return url
    except requests.RequestException:
        pass
    return None


def find_company_logo(page_url: str, timeout: int) -> str | None:
    """A high-resolution site icon for a domain (or a full URL's domain)."""
    dom = page_url if "/" not in page_url else _domain(page_url)
    if not dom:
        return None

    try:
        resp = requests.get(
            f"https://{dom}/", timeout=timeout, headers={"User-Agent": UA}
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for rel in ("apple-touch-icon", "apple-touch-icon-precomposed",
                    "icon", "shortcut icon"):
            el = soup.find("link", rel=lambda v: v and rel in " ".join(
                v if isinstance(v, list) else [v]).lower())
            if el and el.get("href"):
                return urljoin(f"https://{dom}/", el["href"])
    except requests.RequestException:
        pass

    # Google's favicon service is a reliable 256px fallback.
    return f"https://www.google.com/s2/favicons?domain={dom}&sz=256"


# --------------------------------------------------------------------------
# download and validation
# --------------------------------------------------------------------------

def download(url: str, dest: Path, timeout: int) -> Path | None:
    try:
        resp = requests.get(
            url, timeout=timeout, headers={"User-Agent": UA}, stream=True
        )
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "")
        if "image" not in ctype and not re.search(r"\.(png|jpe?g|webp)", url, re.I):
            log.debug("not an image (%s): %s", ctype, url)
            return None
        dest.write_bytes(resp.content)
        return dest
    except (requests.RequestException, OSError) as exc:
        log.debug("download failed %s: %s", url, exc)
        return None


def validate(path: Path, cfg: dict) -> bool:
    """Reject tracking pixels, tiny thumbnails and banner strips."""
    try:
        with Image.open(path) as im:
            w, h = im.size
    except Exception:  # noqa: BLE001 - any decode failure is a reject
        return False

    if w < cfg["min_width"] or h < cfg["min_height"]:
        log.debug("image too small (%dx%d): %s", w, h, path.name)
        return False

    aspect = w / h if h else 0
    if not cfg["min_aspect"] <= aspect <= cfg["max_aspect"]:
        log.debug("image aspect %.2f out of range: %s", aspect, path.name)
        return False
    return True


# --------------------------------------------------------------------------
# composition
# --------------------------------------------------------------------------

def fit_panel(src: Path, dest: Path, width: int, height: int, cfg: dict,
              contain: bool = True) -> Path:
    """Fit `src` into a width x height panel without losing the subject.

    A blurred, darkened copy of the image fills the panel, and the sharp image
    sits centred on top at its natural aspect ratio. Wide press images and
    tall screenshots both land cleanly, and the result reads as deliberate
    rather than as a bad crop.
    """
    with Image.open(src) as im:
        im = im.convert("RGB")

        # --- backdrop: cover the panel, blur, darken ---
        scale = max(width / im.width, height / im.height)
        bw, bh = max(1, int(im.width * scale)), max(1, int(im.height * scale))
        backdrop = im.resize((bw, bh), Image.LANCZOS).crop((
            (bw - width) // 2, (bh - height) // 2,
            (bw - width) // 2 + width, (bh - height) // 2 + height,
        ))
        backdrop = backdrop.filter(ImageFilter.GaussianBlur(cfg["backdrop_blur"]))
        backdrop = ImageEnhance.Brightness(backdrop).enhance(
            1.0 - cfg["backdrop_darken"]
        )

        if contain:
            # If filling the panel only costs a modest crop, fill it - a
            # full-bleed image reads far better than a letterboxed one. Only
            # fall back to letterboxing when cropping would eat the subject.
            crop_loss = 1.0 - min(
                width / (im.width * max(width / im.width, height / im.height)),
                height / (im.height * max(width / im.width, height / im.height)),
            )
            if crop_loss <= cfg.get("max_crop_loss", 0.25):
                # Bias upward for tall images: the subject is usually near the top.
                bias = 0.35 if im.height > im.width else 0.5
                top = int((bh - height) * bias)
                left = (bw - width) // 2
                sharp = im.resize((bw, bh), Image.LANCZOS).crop(
                    (left, top, left + width, top + height)
                )
                backdrop.paste(sharp, (0, 0))
            else:
                fscale = min(width / im.width, height / im.height)
                fw = max(1, int(im.width * fscale))
                fh = max(1, int(im.height * fscale))
                fg = im.resize((fw, fh), Image.LANCZOS)
                backdrop.paste(fg, ((width - fw) // 2, (height - fh) // 2))
        else:
            # Logos: small, centred, never upscaled past 42% of the panel.
            target = int(min(width, height) * 0.42)
            lscale = min(target / im.width, target / im.height, 1.0)
            fw, fh = max(1, int(im.width * lscale)), max(1, int(im.height * lscale))
            fg = im.resize((fw, fh), Image.LANCZOS)
            backdrop.paste(fg, ((width - fw) // 2, (height - fh) // 2))

        backdrop.save(dest, "JPEG", quality=92)
    return dest


# --------------------------------------------------------------------------
# orchestration
# --------------------------------------------------------------------------

def attach_images(stories: list[Story], settings: dict, out_dir: Path) -> None:
    """Populate story.image_path and story.image_kind for every story."""
    cfg = settings["images"]
    if not cfg.get("enabled", True):
        return

    work = out_dir / "images"
    work.mkdir(parents=True, exist_ok=True)

    width = settings["carousel"]["width"]
    height = int(settings["carousel"]["height"] * settings["carousel"]["image_ratio"])
    timeout = cfg["request_timeout_s"]
    mode = cfg.get("mode", "hybrid")

    for idx, story in enumerate(stories):
        raw = work / f"raw_{idx}"
        final = work / f"story_{idx}.jpg"

        # --- 1. official article image --------------------------------------
        if mode in ("hybrid", "official"):
            # Try every clustered source, best-attributed first: if the primary
            # announcement has no image, the press write-up usually does.
            for item in sorted(story.items, key=lambda i: i.source_tier):
                if not item.link or _domain(item.link) in _NO_ARTICLE_IMAGE_DOMAINS:
                    continue
                for candidate in find_article_images(item.link, timeout):
                    # A house share-card is worse than the company's own logo:
                    # it looks like decoration and says nothing about the story.
                    if cfg.get("reject_generic_cards", True) and is_generic_share_card(
                        candidate, item.link, timeout
                    ):
                        continue
                    if download(candidate, raw, timeout) and validate(raw, cfg):
                        fit_panel(raw, final, width, height, cfg, contain=True)
                        story.image_path = str(final)
                        story.image_kind = "official"
                        story.image_credit = item.source_name
                        log.info(
                            "story %d: article image from %s", idx + 1, item.source_name
                        )
                        break
                if story.image_path:
                    break
            if story.image_path:
                continue

        if mode == "official":
            log.warning("story %d: no official image, will be dropped", idx + 1)
            continue

        # Which company is the story actually about? Everything below uses
        # that company's assets, not the reporting outlet's.
        #
        # An explicitly set company always wins. Detection scans for any known
        # brand, so a headline like "Z.ai unveils rival to Claude" would
        # otherwise match Anthropic - the company being compared against
        # rather than the one the story is about.
        detected = detect_company(story) if not story.company else None
        if story.company:
            brand_domain = _domain_for(story.company) or _domain(story.link)
        elif detected:
            story.company, brand_domain = detected
        else:
            brand_domain = _domain(story.link)

        # A bare fallback to the *article's own* domain is only useful when
        # that domain is an actual company's site. For a repository like
        # arXiv it just re-fetches the same site-wide logo we already
        # rejected above (via a different code path) - skip straight to the
        # generated panel instead of showing that logo a second way.
        if brand_domain in _NO_ARTICLE_IMAGE_DOMAINS:
            brand_domain = None

        log.info("story %d: brand imagery from %s", idx + 1, brand_domain or "unknown")

        # --- 2. the company's own hero / product image ----------------------
        if brand_domain:
            brand_url = find_brand_image(brand_domain, timeout)
            if brand_url and download(brand_url, raw, timeout) and validate(raw, cfg):
                fit_panel(raw, final, width, height, cfg, contain=True)
                story.image_path = str(final)
                story.image_kind = "product"
                story.image_credit = story.company or brand_domain
                log.info("story %d: product image from %s", idx + 1, brand_domain)
                continue

        # --- 3. company logo panel ------------------------------------------
        logo_url = find_company_logo(brand_domain, timeout) if brand_domain else None
        if logo_url and download(logo_url, raw, timeout):
            try:
                if validate(raw, {**cfg, "min_width": 96, "min_height": 96,
                                  "min_aspect": 0.2, "max_aspect": 5.0}):
                    fit_panel(raw, final, width, height, cfg, contain=False)
                    story.image_path = str(final)
                    story.image_kind = "logo"
                    story.image_credit = story.company or brand_domain
                    log.info("story %d: logo panel for %s", idx + 1, brand_domain)
                    continue
            except Exception as exc:  # noqa: BLE001
                log.debug("logo composition failed: %s", exc)

        # --- 4. template-rendered branded panel (last resort) ----------------
        story.image_kind = "generated"
        log.info("story %d: no imagery found, using generated panel", idx + 1)


def drop_imageless(stories: list[Story], settings: dict) -> list[Story]:
    """In 'official' mode a story without a real image is not publishable."""
    if settings["images"].get("mode") != "official":
        return stories
    kept = [s for s in stories if s.image_kind == "official"]
    if len(kept) < len(stories):
        log.warning(
            "dropped %d story/stories with no official image (mode=official)",
            len(stories) - len(kept),
        )
    return kept
