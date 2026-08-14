"""Instagram publishing via the Instagram Graph API.

Prerequisites (see SETUP.md):
  * Instagram professional account (Business or Creator) linked to a Facebook Page
  * Page Publishing Authorization completed
  * Permissions: instagram_business_basic, instagram_business_content_publish
  * A long-lived access token

Flow for both media types is the same two-step dance: create a container, then
publish it. Reels containers take time to transcode, so we poll status_code
until FINISHED before publishing.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import requests

from .assets import AssetHost, verify_public
from .models import Edition

log = logging.getLogger(__name__)

API = "https://graph.instagram.com/v21.0"
POLL_INTERVAL_S = 6
POLL_MAX_ATTEMPTS = 60          # reels can take several minutes to transcode


class InstagramError(RuntimeError):
    pass


def _post(path: str, token: str, **params) -> dict:
    params["access_token"] = token
    r = requests.post(f"{API}/{path}", data=params, timeout=60)
    if r.status_code >= 400:
        raise InstagramError(f"POST {path} -> {r.status_code}: {r.text[:400]}")
    return r.json()


def _get(path: str, token: str, **params) -> dict:
    params["access_token"] = token
    r = requests.get(f"{API}/{path}", params=params, timeout=60)
    if r.status_code >= 400:
        raise InstagramError(f"GET {path} -> {r.status_code}: {r.text[:400]}")
    return r.json()


def check_quota(ig_user_id: str, token: str) -> int:
    """Posts used in the trailing 24h. Instagram caps API publishing at 100."""
    data = _get(f"{ig_user_id}/content_publishing_limit", token, fields="quota_usage")
    used = data.get("data", [{}])[0].get("quota_usage", 0)
    log.info("instagram publishing quota used: %s/100", used)
    return used


def _wait_ready(container_id: str, token: str) -> None:
    for attempt in range(POLL_MAX_ATTEMPTS):
        data = _get(container_id, token, fields="status_code,status")
        code = data.get("status_code")
        if code == "FINISHED":
            return
        if code == "ERROR":
            raise InstagramError(f"container {container_id} failed: {data.get('status')}")
        log.info("container %s: %s (%d/%d)", container_id, code, attempt + 1, POLL_MAX_ATTEMPTS)
        time.sleep(POLL_INTERVAL_S)
    raise InstagramError(f"container {container_id} never became ready")


def publish_carousel(
    ig_user_id: str,
    token: str,
    image_urls: list[str],
    caption: str,
) -> str:
    if not 2 <= len(image_urls) <= 10:
        raise InstagramError(f"carousel needs 2-10 images, got {len(image_urls)}")

    for url in image_urls:
        if not verify_public(url):
            raise InstagramError(f"image URL is not publicly reachable: {url}")

    children: list[str] = []
    for url in image_urls:
        res = _post(
            f"{ig_user_id}/media", token,
            image_url=url, is_carousel_item="true",
        )
        children.append(res["id"])
        log.info("carousel item container %s", res["id"])

    for cid in children:
        _wait_ready(cid, token)

    parent = _post(
        f"{ig_user_id}/media", token,
        media_type="CAROUSEL",
        children=",".join(children),
        caption=caption[:2200],
    )
    _wait_ready(parent["id"], token)

    published = _post(f"{ig_user_id}/media_publish", token, creation_id=parent["id"])
    log.info("published carousel: %s", published["id"])
    return published["id"]


def publish_reel(
    ig_user_id: str,
    token: str,
    video_url: str,
    caption: str,
    cover_url: str | None = None,
) -> str:
    if not verify_public(video_url):
        raise InstagramError(f"video URL is not publicly reachable: {video_url}")

    params = {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption[:2200],
        "share_to_feed": "true",
    }
    if cover_url:
        params["cover_url"] = cover_url

    container = _post(f"{ig_user_id}/media", token, **params)
    log.info("reel container %s - waiting for transcode", container["id"])
    _wait_ready(container["id"], token)

    published = _post(f"{ig_user_id}/media_publish", token, creation_id=container["id"])
    log.info("published reel: %s", published["id"])
    return published["id"]


def publish(
    edition: Edition,
    settings: dict,
    slides: list[Path],
    video: Path | None,
    host: AssetHost,
    ig_user_id: str,
    token: str,
) -> dict[str, str]:
    """Upload assets then publish whichever formats are enabled."""
    cfg = settings["publish"]["instagram"]
    results: dict[str, str] = {}

    check_quota(ig_user_id, token)

    if cfg.get("post_carousel", True) and slides:
        urls = [host.upload(p) for p in slides[:10]]
        results["carousel"] = publish_carousel(
            ig_user_id, token, urls, edition.caption
        )

    if cfg.get("post_reel", True) and video and video.exists():
        video_url = host.upload(video)
        results["reel"] = publish_reel(
            ig_user_id, token, video_url, edition.caption
        )

    return results
