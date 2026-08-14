#!/usr/bin/env python3
"""Install your channel avatar as the carousel logo.

    python set_logo.py ~/Downloads/techtales-avatar.png

Takes any image, squares it off, resizes it to 512x512 and writes
assets/logo.png. Every slide picks it up on the next render - no other change
needed.

    python set_logo.py --check     # what is currently installed?
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEST = ROOT / "assets" / "logo.png"
SIZE = 512


def check() -> int:
    if not DEST.exists():
        print(f"No logo installed at {DEST.relative_to(ROOT)}")
        print("Slides will fall back to a text wordmark.")
        return 1
    try:
        from PIL import Image
        with Image.open(DEST) as im:
            print(f"Installed: {DEST.relative_to(ROOT)}  {im.size[0]}x{im.size[1]}  {im.mode}")
    except Exception as exc:  # noqa: BLE001
        print(f"Installed but unreadable: {exc}")
        return 1
    return 0


def install(src: Path) -> int:
    from PIL import Image

    if not src.exists():
        print(f"Not found: {src}")
        return 1

    with Image.open(src) as im:
        im = im.convert("RGBA")

        # Centre-crop to a square so a banner or rectangular export still works.
        side = min(im.size)
        left = (im.width - side) // 2
        top = (im.height - side) // 2
        im = im.crop((left, top, left + side, top + side))
        im = im.resize((SIZE, SIZE), Image.LANCZOS)

        DEST.parent.mkdir(parents=True, exist_ok=True)
        im.save(DEST, "PNG")

    print(f"Installed {src.name} -> {DEST.relative_to(ROOT)} ({SIZE}x{SIZE})")
    print("Preview it with:  python -m aidaily.cli run --dry-run --fixtures")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        raise SystemExit(0)
    if sys.argv[1] == "--check":
        raise SystemExit(check())
    raise SystemExit(install(Path(sys.argv[1]).expanduser()))
