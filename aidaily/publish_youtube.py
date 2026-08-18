"""YouTube Shorts upload via the Data API v3.

A video is treated as a Short automatically when it is vertical and under 60
seconds - there is no "shorts" flag to set. We just upload a normal video.

Two things that surprise people, both handled here:
  * An OAuth project that has not passed Google's API compliance audit has its
    uploads FORCED to private, regardless of what you request. The response is
    checked and logged so this is visible rather than mysterious.
  * Uploads are limited to a small number per day for unaudited projects.
"""

from __future__ import annotations

import logging
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from .models import Edition

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN_URI = "https://oauth2.googleapis.com/token"


def _client(client_id: str, client_secret: str, refresh_token: str):
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=TOKEN_URI,
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )
    creds.refresh(Request())
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def _tags(edition: Edition) -> list[str]:
    base = ["AI", "AI news", "artificial intelligence", "machine learning",
            "tech news", "TechTales", "LLM", "shorts"]
    return base[:15]


def upload(
    edition: Edition,
    settings: dict,
    video: Path,
    client_id: str,
    client_secret: str,
    refresh_token: str,
) -> str:
    cfg = settings["publish"]["youtube"]
    yt = _client(client_id, client_secret, refresh_token)

    body = {
        "snippet": {
            "title": (edition.yt_title or f"AI News - {edition.date}")[:100],
            "description": edition.yt_description[:5000],
            "tags": _tags(edition),
            "categoryId": cfg.get("category_id", "28"),
        },
        "status": {
            "privacyStatus": cfg.get("privacy", "public"),
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(str(video), chunksize=4 * 1024 * 1024, resumable=True)
    request = yt.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    try:
        while response is None:
            status, response = request.next_chunk()
            if status:
                log.info("youtube upload %d%%", int(status.progress() * 100))
    except HttpError as exc:
        raise RuntimeError(f"YouTube upload failed: {exc}") from exc

    video_id = response["id"]
    actual_privacy = response.get("status", {}).get("privacyStatus")
    log.info("uploaded https://youtube.com/shorts/%s (privacy=%s)", video_id, actual_privacy)

    if actual_privacy != cfg.get("privacy", "public"):
        log.warning(
            "YouTube forced privacy to %r instead of %r. This almost always "
            "means the Google Cloud project has not passed the YouTube API "
            "compliance audit. Request an audit, or publish manually until it "
            "clears. See SETUP.md.",
            actual_privacy, cfg.get("privacy"),
        )

    return video_id
