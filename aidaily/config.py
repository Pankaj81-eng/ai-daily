"""Loading of YAML config and environment-backed secrets."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from .models import Source

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
OUT_DIR = Path(os.environ.get("AIDAILY_OUT", ROOT / "out"))
STATE_DIR = Path(os.environ.get("AIDAILY_STATE", ROOT / "state"))


def load_settings(path: Path | None = None) -> dict[str, Any]:
    p = path or CONFIG_DIR / "settings.yaml"
    with open(p) as fh:
        return yaml.safe_load(fh)


def load_sources(path: Path | None = None) -> list[Source]:
    p = path or CONFIG_DIR / "sources.yaml"
    with open(p) as fh:
        raw = yaml.safe_load(fh)
    return [Source(**s) for s in raw["sources"]]


def load_companies(path: Path | None = None) -> list[dict[str, Any]]:
    """Company -> domain map used to pick story-relevant imagery."""
    p = path or CONFIG_DIR / "companies.yaml"
    if not p.exists():
        return []
    with open(p) as fh:
        return (yaml.safe_load(fh) or {}).get("companies", [])


def env(name: str, default: str | None = None, required: bool = False) -> str | None:
    """Read a secret from the environment.

    Everything sensitive is read through here so the required-secret check in
    `cli.doctor` can enumerate them in one place.
    """
    val = os.environ.get(name, default)
    if required and not val:
        raise RuntimeError(
            f"Missing required environment variable {name!r}. "
            f"See SETUP.md for where to get it."
        )
    return val


# Every secret the pipeline can use, and which stage needs it.
SECRETS = {
    "ANTHROPIC_API_KEY": "summarisation",
    "IG_USER_ID": "instagram publishing",
    "IG_ACCESS_TOKEN": "instagram publishing",
    "YT_CLIENT_ID": "youtube publishing",
    "YT_CLIENT_SECRET": "youtube publishing",
    "YT_REFRESH_TOKEN": "youtube publishing",
    "TELEGRAM_BOT_TOKEN": "approval flow",
    "TELEGRAM_CHAT_ID": "approval flow",
    "ASSET_BASE_URL": "public asset hosting (Instagram needs public URLs)",
}
