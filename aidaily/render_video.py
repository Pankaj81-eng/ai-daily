"""Stage 4b - render the vertical short for Reels / YouTube Shorts.

Approach: split the edition into narration segments (cover + one per story),
synthesise each with edge-tts, measure the real audio duration, render a
matching 1080x1920 frame, then let ffmpeg assemble stills + a slow zoom into a
single MP4. Timing therefore follows the voiceover rather than a guess.

Requires ffmpeg on PATH.
"""

from __future__ import annotations

import asyncio
import json
import logging

import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import ROOT
from .models import Edition

log = logging.getLogger(__name__)

MIN_SEGMENT_S = 2.2
PAD_S = 0.28          # breathing room appended to each segment


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(ROOT / "templates"),
        autoescape=select_autoescape(["html"]),
    )


def _require_ffmpeg() -> None:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found on PATH - install it (apt install ffmpeg)")


def _segments(edition: Edition) -> list[str]:
    """One narration chunk per frame, in frame order.

    Narration is authored per story upstream, so this is a straight read
    rather than a re-split - which is what keeps the audio describing the
    story actually on screen.
    """
    segs = [edition.intro_line or f"Here is your AI news for {edition.date}."]
    for story in edition.stories:
        segs.append(story.script_line or f"{story.headline}. {story.body}")
    return segs


async def _tts_edge(text: str, out: Path, voice: str, rate: str) -> None:
    import edge_tts

    comm = edge_tts.Communicate(text, voice, rate=rate)
    await comm.save(str(out))


def _tts_espeak(text: str, out: Path) -> None:
    """Offline fallback. Robotic, but it keeps the pipeline running."""
    wav = out.with_suffix(".wav")
    subprocess.run(
        ["espeak-ng", "-v", "en-us", "-s", "155", "-p", "45",
         "-w", str(wav), text],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav),
         "-codec:a", "libmp3lame", "-b:a", "192k", str(out)],
        check=True,
    )
    wav.unlink(missing_ok=True)


def synth(text: str, out: Path, settings: dict) -> None:
    """Speak `text` into `out` (mp3), degrading gracefully.

    edge-tts uses an undocumented Microsoft endpoint. It is free and sounds
    good, but it does break without warning, so a local engine backs it up
    rather than letting one bad morning kill the whole run.
    """
    vcfg = settings["video"]
    engine = vcfg.get("tts_engine", "edge")

    if engine == "edge":
        try:
            asyncio.run(_tts_edge(text, out, vcfg["tts_voice"], vcfg["tts_rate"]))
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("edge-tts failed (%s) - falling back to espeak-ng", exc)

    if shutil.which("espeak-ng"):
        _tts_espeak(text, out)
        return

    raise RuntimeError(
        "No working TTS engine. edge-tts failed and espeak-ng is not "
        "installed (apt install espeak-ng)."
    )


def _duration(path: Path) -> float:
    res = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(res.stdout)["format"]["duration"])


def _frame_specs(edition: Edition, settings: dict) -> list[dict]:
    brand = settings["brand"]
    total = len(edition.stories) + 1
    date_label = datetime.strptime(edition.date, "%Y-%m-%d").strftime("%d %B %Y")
    common = {
        "w": settings["video"]["width"],
        "h": settings["video"]["height"],
        "c": brand,
        "brand_name": brand["name"],
        "handle": brand["handle"],
        "date_label": date_label,
    }

    specs = [{
        **common, "kind": "cover",
        "title": edition.intro or "Today in AI",
        "subtitle": f"{len(edition.stories)} verified stories in under a minute.",
        "sources": "Primary sources in description",
        "progress": round(100 / total, 1),
    }]

    for i, story in enumerate(edition.stories, start=1):
        specs.append({
            **common, "kind": "story", "index": i,
            "title": story.headline,
            "subtitle": story.body,
            "sources": ", ".join(story.sources[:2]),
            "progress": round(100 * (i + 1) / total, 1),
        })
    return specs


def render(edition: Edition, settings: dict, out_dir: Path) -> Path:
    """Produce out_dir/short.mp4 and return its path."""
    _require_ffmpeg()
    from playwright.sync_api import sync_playwright

    vcfg = settings["video"]
    out_dir = out_dir.resolve()          # frames are loaded as file:// URIs
    work = out_dir / "video"
    work.mkdir(parents=True, exist_ok=True)

    chunks = _segments(edition)
    specs = _frame_specs(edition, settings)
    n = min(len(chunks), len(specs))
    chunks, specs = chunks[:n], specs[:n]

    # ---- 1. voiceover per segment -----------------------------------------
    audio_paths: list[Path] = []
    durations: list[float] = []
    for i, text in enumerate(chunks):
        mp3 = work / f"seg_{i:02d}.mp3"
        speech = text.strip() or "..."
        synth(speech, mp3, settings)
        audio_paths.append(mp3)
        durations.append(_duration(mp3))
        log.info("segment %d: %.2fs  %s", i, durations[-1], speech[:52])

    # ---- 1b. enforce the duration ceiling ----------------------------------
    # A Short that runs long gets treated as a regular video, so the cap is
    # enforced by speeding the narration rather than merely warning about it.
    budget = vcfg["max_duration_s"] - PAD_S * len(durations)
    raw_total = sum(durations)
    tempo = 1.0
    if raw_total > budget:
        tempo = min(1.35, raw_total / budget)
        log.warning(
            "narration is %.1fs against a %ss ceiling - speeding voiceover by "
            "%.2fx. Lower summarize.script_target_words for a calmer read.",
            raw_total, vcfg["max_duration_s"], tempo,
        )
        for i, mp3 in enumerate(audio_paths):
            fast = mp3.with_name(f"fast_{mp3.name}")
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3),
                 "-filter:a", f"atempo={tempo:.4f}",
                 "-c:a", "libmp3lame", "-b:a", "192k", str(fast)],
                check=True,
            )
            audio_paths[i] = fast
            durations[i] = _duration(fast)

    durations = [max(MIN_SEGMENT_S, d + PAD_S) for d in durations]
    log.info("final runtime: %.1fs across %d segments", sum(durations), len(durations))

    # ---- 2. frames ---------------------------------------------------------
    tpl = _env().get_template("frame.html.j2")
    frame_paths: list[Path] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--font-render-hinting=none"])
        page = browser.new_page(
            viewport={"width": vcfg["width"], "height": vcfg["height"]},
            device_scale_factor=1,
        )
        for i, spec in enumerate(specs):
            html = work / f"frame_{i:02d}.html"
            html.write_text(tpl.render(**spec), encoding="utf-8")
            page.goto(html.as_uri())
            page.wait_for_timeout(650)
            png = work / f"frame_{i:02d}.png"
            page.screenshot(path=str(png))
            frame_paths.append(png)
        browser.close()

    # ---- 3. one clip per segment, with a slow zoom -------------------------
    fps = vcfg["fps"]
    clips: list[Path] = []
    for i, (png, dur) in enumerate(zip(frame_paths, durations)):
        clip = work / f"clip_{i:02d}.mp4"
        frames = max(1, int(round(dur * fps)))
        # zoompan samples from an upscaled copy so the slow push stays sharp.
        # 1.5x is enough headroom for a 1.09 zoom and renders far faster than 2x.
        vf = (
            f"scale={int(vcfg['width']*1.5)}:{int(vcfg['height']*1.5)},"
            f"zoompan=z='min(zoom+0.00045,1.09)':d={frames}"
            f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":s={vcfg['width']}x{vcfg['height']}:fps={fps},"
            f"format=yuv420p"
        )
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(png),
             "-i", str(audio_paths[i]),
             "-vf", vf,
             "-af", f"apad=pad_dur={PAD_S + 0.5}",
             "-t", f"{dur:.3f}",
             "-c:v", "libx264", "-preset", "medium", "-crf", "20",
             "-r", str(fps), "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
             str(clip)],
            check=True,
        )
        clips.append(clip)

    # ---- 4. concat ---------------------------------------------------------
    # Every clip was encoded with identical parameters, so the streams can be
    # copied rather than re-encoded: faster, and no generational quality loss.
    listfile = work / "concat.txt"
    listfile.write_text("".join(f"file '{c.name}'\n" for c in clips))
    out = out_dir / "short.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", str(listfile), "-c", "copy",
         "-movflags", "+faststart", str(out)],
        check=True, cwd=work,
    )

    log.info("video rendered: %s (%.1fs)", out, _duration(out))
    return out
