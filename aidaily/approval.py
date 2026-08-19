"""Human-in-the-loop approval over Telegram.

The job builds everything, sends you the actual slides and the actual video
with two buttons, and blocks until you tap one (or the window expires, which
counts as a no). Nothing reaches your audience that you have not looked at.

Telegram is used rather than email because it renders the media inline on a
phone and gives real tap-to-confirm buttons with no server to host.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import requests

from .models import Edition

log = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/{method}"
POLL_INTERVAL_S = 5


class ApprovalTimeout(RuntimeError):
    pass


def _call(token: str, method: str, files=None, **payload) -> dict:
    r = requests.post(
        API.format(token=token, method=method),
        data=payload, files=files, timeout=120,
    )
    body = r.json()
    if not body.get("ok"):
        raise RuntimeError(f"telegram {method} failed: {json.dumps(body)[:400]}")
    return body["result"]


def _digest(edition: Edition) -> str:
    lines = [f"*TechTales - {edition.date}*", ""]
    for i, s in enumerate(edition.stories, 1):
        srcs = ", ".join(s.sources[:3])
        lines.append(f"{i}. *{s.headline}*")
        lines.append(f"   {s.body}")
        lines.append(f"   _tier {s.best_tier} · {s.corroboration} source(s): {srcs}_")
        lines.append(f"   {s.link}")
        lines.append("")
    return "\n".join(lines)[:4000]


def send_preview(
    token: str,
    chat_id: str,
    edition: Edition,
    slides: list[Path],
    video: Path | None,
) -> str:
    """Send the full draft. Returns the message id carrying the buttons."""
    _call(token, "sendMessage", chat_id=chat_id, text=_digest(edition),
          parse_mode="Markdown", disable_web_page_preview=True)

    if slides:
        media, files = [], {}
        for i, p in enumerate(slides[:10]):
            key = f"photo{i}"
            media.append({"type": "photo", "media": f"attach://{key}"})
            files[key] = (p.name, p.open("rb"), "image/png")
        try:
            _call(token, "sendMediaGroup", chat_id=chat_id,
                  media=json.dumps(media), files=files)
        finally:
            for _, fh, _ in files.values():
                fh.close()

    if video and video.exists():
        with video.open("rb") as fh:
            _call(token, "sendVideo", chat_id=chat_id,
                  caption="YouTube video preview",
                  files={"video": (video.name, fh, "video/mp4")})

    keyboard = {
        "inline_keyboard": [[
            {"text": "Publish", "callback_data": "approve"},
            {"text": "Discard", "callback_data": "reject"},
        ]]
    }
    msg = _call(
        token, "sendMessage", chat_id=chat_id,
        text="Publish this to Instagram and YouTube?",
        reply_markup=json.dumps(keyboard),
    )
    return str(msg["message_id"])


def wait_for_decision(token: str, chat_id: str, timeout_s: int = 2700) -> bool:
    """Poll for a button tap. True = publish. Timeout = do not publish."""
    deadline = time.time() + timeout_s
    offset = None

    # Drain anything already queued so a stale tap can't auto-approve today.
    pre = _call(token, "getUpdates", timeout=0)
    if pre:
        offset = pre[-1]["update_id"] + 1

    log.info("waiting up to %d min for approval", timeout_s // 60)
    while time.time() < deadline:
        params = {"timeout": 25}
        if offset is not None:
            params["offset"] = offset
        try:
            updates = _call(token, "getUpdates", **params)
        except RuntimeError as exc:
            log.warning("getUpdates hiccup: %s", exc)
            time.sleep(POLL_INTERVAL_S)
            continue

        for upd in updates:
            offset = upd["update_id"] + 1
            cb = upd.get("callback_query")
            if not cb:
                continue
            if str(cb["message"]["chat"]["id"]) != str(chat_id):
                continue

            decision = cb["data"]
            _call(token, "answerCallbackQuery", callback_query_id=cb["id"],
                  text="Publishing..." if decision == "approve" else "Discarded.")
            _call(token, "editMessageText", chat_id=chat_id,
                  message_id=cb["message"]["message_id"],
                  text="Approved - publishing now."
                  if decision == "approve" else "Discarded. Nothing was posted.")
            log.info("decision received: %s", decision)
            return decision == "approve"

        time.sleep(POLL_INTERVAL_S)

    _call(token, "sendMessage", chat_id=chat_id,
          text="No response in time - nothing was published today.")
    raise ApprovalTimeout("approval window expired")


def notify(token: str, chat_id: str, text: str) -> None:
    try:
        _call(token, "sendMessage", chat_id=chat_id, text=text[:4000],
              disable_web_page_preview=True)
    except RuntimeError as exc:
        log.warning("could not send notification: %s", exc)
