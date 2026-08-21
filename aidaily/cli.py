"""Pipeline orchestrator.

  python -m aidaily.cli run --dry-run     build everything, publish nothing
  python -m aidaily.cli run               build, ask on Telegram, publish
  python -m aidaily.cli run --no-approval build and publish immediately
  python -m aidaily.cli doctor            check config and secrets
  python -m aidaily.cli sources           check every feed is alive
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from . import (
    approval, editorial, images, ingest, render_carousel, render_video, summarize, verify,
)
from .config import OUT_DIR, SECRETS, env, load_settings, load_sources
from .models import Edition
from .state import PublishedLog, SeenStore

log = logging.getLogger("aidaily")


class NoNewsletterToday(Exception):
    """Nothing cleared the editorial bar today. This is a normal, expected,
    frequent outcome under the "publish nothing rather than noise" policy -
    not a crash. Kept as its own exception (rather than a bare SystemExit,
    which every other failure in build() also raises) so cmd_run can tell
    "we correctly chose not to publish" apart from "something actually broke",
    and notify Telegram accordingly instead of going silent either way."""


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)-22s %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("googleapiclient").setLevel(logging.WARNING)


def _attach_sample_images(stories, settings: dict, out_dir: Path) -> None:
    """Offline stand-in for image discovery, used by --fixtures.

    Runs the real compositing path over deliberately awkward aspect ratios so
    template work can be checked without network access.
    """
    from tests.fixtures import sample_images

    work = out_dir / "images"
    samples = sample_images(work / "src")
    width = settings["carousel"]["width"]
    height = int(settings["carousel"]["height"] * settings["carousel"]["image_ratio"])

    for i, story in enumerate(stories):
        src = samples[i % len(samples)]
        dest = work / f"story_{i}.jpg"
        images.fit_panel(src, dest, width, height, settings["images"], contain=True)
        story.image_path = str(dest)
        story.image_kind = "official"
        story.image_credit = story.lead.source_name
    log.warning("using SAMPLE images - no network fetch")


def build(
    settings: dict, date: str, out_dir: Path, use_fixtures: bool = False
) -> tuple[Edition, list[Path], Path | None]:
    """Everything up to but not including publishing."""
    if use_fixtures:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from tests.fixtures import items as fixture_items

        log.warning("using FIXTURE data - no network fetch")
        items = fixture_items()
    else:
        sources = load_sources()
        items = ingest.fetch_all(sources, settings)
    if not items:
        raise SystemExit("No items ingested. Check network or feed URLs (`sources` cmd).")

    primaries = verify.primary_domains(items)
    stories = verify.cluster(items, settings["verify"]["cluster_similarity"])
    verified = verify.verify(stories, settings, primaries)

    seen = SeenStore()
    candidates = verify.top_candidates(
        verified, seen, limit=settings["verify"].get("editorial_pool_size", 40)
    )
    if not candidates:
        raise NoNewsletterToday("Nothing new passed verification today.")

    chosen = editorial.select_story(candidates, settings, PublishedLog().recent())
    if chosen is None:
        raise NoNewsletterToday(
            "Editorial gate: no candidate cleared the bar today - "
            "publishing nothing rather than noise."
        )
    selected = [chosen]

    out_dir.mkdir(parents=True, exist_ok=True)

    # Images first: in "official" mode a story with no usable visual is not
    # publishable, and dropping it before the copywriting call saves tokens.
    if use_fixtures:
        _attach_sample_images(selected, settings, out_dir)
    else:
        images.attach_images(selected, settings, out_dir)
    selected = images.drop_imageless(selected, settings)
    if not selected:
        raise NoNewsletterToday(
            f"Today's chosen story ({chosen.headline or chosen.title}) had no "
            "usable image. Not posting - not falling back to a lower-quality "
            "candidate, since that would undercut the editorial pick."
        )

    edition = summarize.summarize(selected, settings, date)
    (out_dir / "edition.json").write_text(json.dumps(edition.to_dict(), indent=2))

    slides = render_carousel.render(edition, settings, out_dir)

    video = None
    if settings["video"].get("enabled", True):
        try:
            # "slideshow" (default): the same 4 carousel images, no spoken
            # narration - see aidaily.render_video.render_slideshow(). The
            # original AI-voiced short is still there, just not the default;
            # switch settings.video.style back to "narrated" to use it again.
            if settings["video"].get("style", "slideshow") == "narrated":
                video = render_video.render(edition, settings, out_dir)
            else:
                video = render_video.render_slideshow(edition, settings, out_dir, slides)
        except Exception as exc:  # noqa: BLE001 - a failed video must not kill the carousel
            log.error("video render failed, continuing with carousel only: %s", exc)

    return edition, slides, video


def cmd_run(args: argparse.Namespace) -> int:
    settings = load_settings()
    date = args.date or datetime.now().strftime("%Y-%m-%d")
    out_dir = Path(args.out) if args.out else OUT_DIR / date

    try:
        edition, slides, video = build(settings, date, out_dir, args.fixtures)
    except NoNewsletterToday as exc:
        # A legitimate, expected outcome under "publish nothing rather than
        # noise" - not a failure. Say so on Telegram (so a quiet morning
        # reads as "checked and nothing qualified", not "the job silently
        # died") and exit 0, so this never gets flagged next to real crashes.
        log.info("no newsletter today - %s", exc)
        tg_token, tg_chat = env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_CHAT_ID")
        if tg_token and tg_chat:
            approval.notify(
                tg_token, tg_chat,
                f"No newsletter today.\n\n{exc}\n\nThis is expected - nothing "
                f"cleared the bar, so nothing was published.",
            )
        return 0

    log.info("built %d slides%s in %s", len(slides),
             " + video" if video else "", out_dir)
    for s in edition.stories:
        log.info("  [tier %d, %dx] %s", s.best_tier, s.corroboration, s.headline)

    if args.dry_run:
        log.info("dry run - nothing published. Inspect %s", out_dir)
        return 0

    tg_token = env("TELEGRAM_BOT_TOKEN")
    tg_chat = env("TELEGRAM_CHAT_ID")

    if not args.no_approval:
        if not (tg_token and tg_chat):
            log.error("approval requested but Telegram secrets are missing")
            return 2
        approval.send_preview(tg_token, tg_chat, edition, slides, video)
        try:
            if not approval.wait_for_decision(tg_token, tg_chat, args.approval_timeout):
                log.info("rejected - nothing published")
                return 0
        except approval.ApprovalTimeout:
            log.info("approval timed out - nothing published")
            return 0

    # ---------------- publish ----------------
    from .assets import build_host

    results: dict[str, str] = {}
    host = build_host(date)

    ig = settings["publish"]["instagram"]
    if ig.get("enabled"):
        from . import publish_instagram
        try:
            results |= publish_instagram.publish(
                edition, settings, slides, video, host,
                env("IG_USER_ID", required=True), env("IG_ACCESS_TOKEN", required=True),
            )
        except Exception as exc:  # noqa: BLE001
            log.error("instagram publish failed: %s", exc)
            results["instagram_error"] = str(exc)[:300]

    yt = settings["publish"]["youtube"]
    if yt.get("enabled") and video:
        from . import publish_youtube
        try:
            results["youtube"] = publish_youtube.upload(
                edition, settings, video,
                env("YT_CLIENT_ID", required=True),
                env("YT_CLIENT_SECRET", required=True),
                env("YT_REFRESH_TOKEN", required=True),
            )
        except Exception as exc:  # noqa: BLE001
            log.error("youtube publish failed: %s", exc)
            results["youtube_error"] = str(exc)[:300]

    # Only remember stories that actually went out.
    if any(k in results for k in ("carousel", "reel", "youtube")):
        seen = SeenStore()
        published_log = PublishedLog()
        for story in edition.stories:
            seen.add_many([i.uid for i in story.items])
            published_log.add(date, story.headline, story.company, story.category)
        seen.save()
        published_log.save()

    (out_dir / "results.json").write_text(json.dumps(results, indent=2))
    log.info("results: %s", json.dumps(results, indent=2))

    if tg_token and tg_chat:
        approval.notify(tg_token, tg_chat, f"Done.\n{json.dumps(results, indent=2)}")

    return 1 if any(k.endswith("_error") for k in results) else 0


def cmd_doctor(args: argparse.Namespace) -> int:
    settings = load_settings()
    sources = load_sources()
    print(f"settings loaded   : {len(settings)} sections")
    print(f"sources allowlist : {len(sources)} feeds "
          f"({sum(1 for s in sources if s.tier == 1)} tier-1)")
    print(f"seen store        : {len(SeenStore())} remembered items")
    print("\nsecrets:")
    missing = []
    for name, purpose in SECRETS.items():
        ok = bool(env(name))
        print(f"  [{'x' if ok else ' '}] {name:<22} {purpose}")
        if not ok:
            missing.append(name)
    if missing:
        print(f"\n{len(missing)} missing. Dry runs work without them; "
              f"publishing does not.")
    import shutil
    print(f"\nffmpeg            : {shutil.which('ffmpeg') or 'NOT FOUND'}")
    return 0


def cmd_sources(args: argparse.Namespace) -> int:
    settings = load_settings()
    sources = load_sources()
    bad = 0
    for src in sorted(sources, key=lambda s: s.tier):
        items = ingest.fetch_source(src, settings)
        flag = "ok " if items else "EMPTY"
        if not items:
            bad += 1
        print(f"  [{flag}] tier{src.tier}  {src.name:<26} {len(items):>3} recent items")
    print(f"\n{len(sources) - bad}/{len(sources)} feeds returned recent items.")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="aidaily")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="build and publish today's edition")
    r.add_argument("--dry-run", action="store_true", help="build only, publish nothing")
    r.add_argument("--no-approval", action="store_true", help="skip the Telegram gate")
    r.add_argument("--approval-timeout", type=int, default=2700, help="seconds to wait")
    r.add_argument("--fixtures", action="store_true",
                   help="use bundled sample stories instead of live feeds "
                        "(handy for restyling the templates offline)")
    r.add_argument("--date", help="YYYY-MM-DD, defaults to today")
    r.add_argument("--out", help="output directory")
    r.set_defaults(func=cmd_run)

    d = sub.add_parser("doctor", help="check config and secrets")
    d.set_defaults(func=cmd_doctor)

    s = sub.add_parser("sources", help="check every feed is alive")
    s.set_defaults(func=cmd_sources)

    args = p.parse_args(argv)
    _setup_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
