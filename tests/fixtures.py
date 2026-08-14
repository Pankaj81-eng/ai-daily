"""Synthetic but realistic feed items.

Used by `--fixtures` so you can exercise and restyle the whole pipeline
without waiting for real news, and by the test suite to assert the
verification rules behave.

The set is deliberately adversarial: it contains a clean primary
announcement, the same story reported by two outlets, a single-outlet rumour
that MUST be rejected, an aggregator-only item that MUST be rejected, and a
press story whose only credential is a link to a primary source.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from aidaily.models import Item


def _ago(hours: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=hours)


def items() -> list[Item]:
    return [
        # --- 1. clean tier-1 primary announcement -------------------------
        Item(
            title="Introducing a faster, cheaper embedding model for retrieval",
            link="https://openai.com/blog/new-embedding-model",
            summary=(
                "We are releasing a new text embedding model that matches the "
                "retrieval quality of our previous generation at roughly one "
                "third of the cost. It supports 8192-token inputs and is "
                "available today in the API."
            ),
            published=_ago(5),
            source_name="OpenAI Blog",
            source_tier=1,
            tags=["lab"],
        ),
        # --- 2. same story, two independent tier-2 reports ----------------
        Item(
            title="EU AI Act enforcement body publishes first compliance guidance",
            link="https://techcrunch.com/eu-ai-act-guidance",
            summary=(
                "The European AI Office has published its first set of "
                "compliance guidance for general-purpose AI model providers, "
                "covering documentation, copyright policy and systemic risk "
                "assessment obligations."
            ),
            published=_ago(9),
            source_name="TechCrunch AI",
            source_tier=2,
            tags=["press"],
        ),
        Item(
            title="Europe issues first compliance guidance under the AI Act",
            link="https://arstechnica.com/eu-ai-office-guidance",
            summary=(
                "Providers of general-purpose AI models now have concrete "
                "documentation requirements, following guidance published by "
                "the European AI Office this week."
            ),
            published=_ago(8),
            source_name="Ars Technica AI",
            source_tier=2,
            tags=["press"],
        ),
        # --- 3. tier-2 single report, but links to a primary source -------
        Item(
            title="Nvidia details next-generation inference accelerator",
            link="https://www.theverge.com/nvidia-inference-chip",
            summary=(
                "Nvidia has published architectural details of its next "
                "inference-focused accelerator, claiming improved throughput "
                "per watt on large language model serving workloads."
            ),
            published=_ago(11),
            source_name="The Verge AI",
            source_tier=2,
            tags=["press"],
            outlinks=["https://blogs.nvidia.com/blog/inference-accelerator/"],
        ),
        # anchor so blogs.nvidia.com registers as a primary domain
        Item(
            title="Announcing our next-generation inference platform",
            link="https://blogs.nvidia.com/blog/inference-accelerator/",
            summary="Architectural detail on our new inference accelerator.",
            published=_ago(12),
            source_name="NVIDIA Blog",
            source_tier=1,
            tags=["hardware"],
        ),
        # --- 4. tier-1 research -------------------------------------------
        Item(
            title="Sparse attention routing reduces long-context inference cost",
            link="https://arxiv.org/abs/2508.01234",
            summary=(
                "We present a routing method that selects a sparse subset of "
                "attention heads per token, cutting long-context inference "
                "cost substantially while matching dense baselines on "
                "retrieval benchmarks."
            ),
            published=_ago(14),
            source_name="arXiv cs.LG",
            source_tier=1,
            tags=["research"],
        ),
        # --- 5. tier-1 open weights ---------------------------------------
        Item(
            title="Open-weights model family released with permissive licence",
            link="https://huggingface.co/blog/open-weights-release",
            summary=(
                "A new family of open-weight language models has been released "
                "under a permissive licence, spanning 1B to 40B parameters, "
                "with published training data documentation."
            ),
            published=_ago(6),
            source_name="Hugging Face Blog",
            source_tier=1,
            tags=["openweights"],
        ),
        # --- REJECT: lone tier-2 rumour, no corroboration, no primary link -
        Item(
            title="Startup reportedly in talks for a funding round, sources say",
            link="https://venturebeat.com/rumour-funding",
            summary=(
                "An AI startup is reportedly in early talks for a new funding "
                "round, according to people familiar with the matter. Terms "
                "could change and no agreement has been signed."
            ),
            published=_ago(4),
            source_name="VentureBeat AI",
            source_tier=2,
            tags=["press"],
        ),
        # --- REJECT: aggregator only --------------------------------------
        Item(
            title="Show HN: I built an AI agent that runs my entire company",
            link="https://news.ycombinator.com/item?id=99999",
            summary="Discussion thread about a personal project.",
            published=_ago(3),
            source_name="Hacker News (AI front page)",
            source_tier=3,
            tags=["aggregator"],
        ),
    ]


def sample_images(dest: Path) -> list[Path]:
    """Stand-in "official" images for offline previews.

    These imitate the kinds of visuals real announcements actually ship - a
    product UI screenshot, a hardware die shot, a mobile app capture - in the
    awkward aspect ratios press assets come in (1.91:1 share card, square,
    tall). Abstract artwork would make the preview look nothing like a live
    run, and would hide cropping problems the real thing would expose.
    """
    from PIL import Image, ImageDraw

    dest.mkdir(parents=True, exist_ok=True)
    out = []

    def bg(w, h, top, bot):
        im = Image.new("RGB", (w, h), top)
        d = ImageDraw.Draw(im)
        for y in range(h):
            t = y / max(1, h - 1)
            d.line([(0, y), (w, y)],
                   fill=tuple(int(top[k] + (bot[k] - top[k]) * t) for k in range(3)))
        return im

    # --- 1. wide: a desktop product UI screenshot -------------------------
    w, h = 1200, 630
    im = bg(w, h, (22, 18, 54), (10, 9, 26)); d = ImageDraw.Draw(im)
    win = (90, 78, w - 90, h - 78)
    d.rounded_rectangle(win, 16, fill=(19, 20, 44), outline=(96, 84, 200), width=2)
    d.rounded_rectangle((win[0], win[1], win[2], win[1] + 52), 16, fill=(30, 28, 66))
    for i, col in enumerate([(236, 106, 94), (238, 190, 82), (106, 202, 122)]):
        d.ellipse((win[0] + 22 + i * 26, win[1] + 20, win[0] + 34 + i * 26, win[1] + 32), fill=col)
    d.rectangle((win[0] + 2, win[1] + 54, win[0] + 210, win[3] - 2), fill=(24, 23, 56))
    for i in range(6):
        y = win[1] + 92 + i * 46
        d.rounded_rectangle((win[0] + 26, y, win[0] + 180, y + 20), 6,
                            fill=(124, 92, 255) if i == 1 else (58, 56, 104))
    for i in range(5):
        y = win[1] + 96 + i * 54
        d.rounded_rectangle((win[0] + 250, y, win[2] - 60 - (i % 3) * 90, y + 22), 8,
                            fill=(150, 146, 210) if i % 2 == 0 else (86, 82, 150))
    for i, bh in enumerate([70, 120, 95, 165, 130]):
        x = win[0] + 260 + i * 92
        d.rounded_rectangle((x, win[3] - 60 - bh, x + 58, win[3] - 60), 7,
                            fill=(124, 92, 255) if i == 3 else (70, 62, 150))
    p1 = dest / "sample_wide.jpg"; im.save(p1, "JPEG", quality=92); out.append(p1)

    # --- 2. square: a chip / accelerator die shot --------------------------
    w = h = 900
    im = bg(w, h, (18, 14, 44), (8, 8, 22)); d = ImageDraw.Draw(im)
    d.rounded_rectangle((150, 150, 750, 750), 28, fill=(26, 24, 62), outline=(130, 100, 255), width=3)
    for i in range(4):
        for j in range(4):
            x, y = 196 + i * 140, 196 + j * 140
            shade = 200 - (i + j) * 14
            d.rounded_rectangle((x, y, x + 108, y + 108), 12,
                                fill=(int(shade * 0.42), int(shade * 0.34), shade))
    for i in range(12):
        d.rectangle((150 + i * 50 + 14, 118, 150 + i * 50 + 36, 148), fill=(150, 140, 220))
        d.rectangle((150 + i * 50 + 14, 752, 150 + i * 50 + 36, 782), fill=(150, 140, 220))
    p2 = dest / "sample_square.jpg"; im.save(p2, "JPEG", quality=92); out.append(p2)

    # --- 3. tall: a mobile app screenshot ---------------------------------
    w, h = 900, 1400
    im = bg(w, h, (16, 14, 46), (9, 8, 24)); d = ImageDraw.Draw(im)
    ph = (170, 120, 730, 1280)
    d.rounded_rectangle(ph, 48, fill=(20, 20, 48), outline=(120, 96, 250), width=3)
    d.rounded_rectangle((370, 142, 530, 166), 12, fill=(60, 56, 110))
    for i in range(7):
        y = 230 + i * 132
        right = i % 2 == 0
        x0 = 320 if right else 210
        x1 = 690 if right else 570
        d.rounded_rectangle((x0, y, x1, y + 96), 20,
                            fill=(124, 92, 255) if right else (44, 42, 92))
        for k in range(2):
            d.rounded_rectangle((x0 + 24, y + 26 + k * 30, x1 - 40 - k * 60, y + 42 + k * 30),
                                6, fill=(235, 230, 255) if right else (120, 116, 180))
    p3 = dest / "sample_tall.jpg"; im.save(p3, "JPEG", quality=92); out.append(p3)

    return out
