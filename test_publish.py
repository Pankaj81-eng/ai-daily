"""One-off script to test the real Instagram publish path from your own
machine (see GO_LIVE.md).

It does exactly what the daily pipeline would do at the publish stage:
  1. Uploads the 6 approved slide JPEGs to a public GitHub Release (so
     Instagram's servers can fetch them by URL).
  2. Calls the real Instagram Graph API to build the carousel container and
     publish it.

Nothing here reads live news or re-renders anything - it publishes whatever
JPEGs you point it at, so you know exactly what's about to go live before
you run it.

Usage:
    export IG_ACCESS_TOKEN="..."
    export IG_USER_ID="..."
    export GITHUB_REPOSITORY="yourname/ai-daily"   # must be PUBLIC
    export GH_TOKEN="ghp_..."                       # a PAT with 'repo' scope

    python test_publish.py editions/2026-08-14.json out/2026-08-14
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from aidaily.assets import build_host
from aidaily.config import load_settings
from aidaily.publish_instagram import InstagramError, publish
from make_edition import build_edition


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("edition_json", help="e.g. editions/2026-08-14.json")
    ap.add_argument("slides_dir", help="e.g. out/2026-08-14 (folder with slide_00.jpg..slide_05.jpg)")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = ap.parse_args()

    for var in ("IG_ACCESS_TOKEN", "IG_USER_ID", "GITHUB_REPOSITORY", "GH_TOKEN"):
        if not os.environ.get(var):
            sys.exit(f"Missing required env var: {var}. See GO_LIVE.md.")

    settings = load_settings()
    data = json.loads(Path(args.edition_json).read_text())
    edition = build_edition(data, settings)

    slides_dir = Path(args.slides_dir)
    slides = sorted(slides_dir.glob("slide_0*.jpg"))
    if len(slides) < 2:
        sys.exit(f"Expected slide_00.jpg.. in {slides_dir}, found {len(slides)}. "
                  f"Render first with: python make_edition.py {args.edition_json} --no-video")

    print(f"About to publish {len(slides)} slides to Instagram user {os.environ['IG_USER_ID']}:")
    for s in slides:
        print(f"  - {s.name}")
    print(f"\nCaption:\n{edition.caption}\n")

    if not args.yes:
        reply = input("Type PUBLISH to go live, anything else to cancel: ")
        if reply.strip() != "PUBLISH":
            print("Cancelled. Nothing was posted.")
            return

    host = build_host(edition.date)

    try:
        results = publish(
            edition=edition,
            settings=settings,
            slides=slides,
            video=None,
            host=host,
            ig_user_id=os.environ["IG_USER_ID"],
            token=os.environ["IG_ACCESS_TOKEN"],
        )
    except InstagramError as exc:
        sys.exit(f"Instagram rejected the publish: {exc}")

    print("\nPublished:")
    for kind, media_id in results.items():
        print(f"  {kind}: {media_id}")
    print(f"\nCheck it live: https://www.instagram.com/techtalesengineering/")


if __name__ == "__main__":
    main()
