"""Public hosting for rendered media.

Instagram's Content Publishing API does not accept file uploads for images - it
fetches `image_url` / `video_url` from a public HTTPS endpoint. So whatever we
render has to be reachable on the open internet for a few minutes.

Two adapters:
  github_release  push assets to a GitHub Release on a PUBLIC repo. Free, no
                  extra account, URLs are live immediately. Default.
  s3              any S3-compatible bucket (AWS S3, Cloudflare R2, Backblaze).
                  Use this if you want the repo private.
"""

from __future__ import annotations

import logging
import mimetypes
import os
import subprocess
from pathlib import Path

import requests

log = logging.getLogger(__name__)


class AssetHost:
    def upload(self, path: Path) -> str:  # pragma: no cover - interface
        raise NotImplementedError


class GitHubReleaseHost(AssetHost):
    """Uploads via the `gh` CLI, which is preinstalled on Actions runners."""

    def __init__(self, repo: str, tag: str, token: str):
        self.repo = repo
        self.tag = tag
        self.token = token
        self._ensured = False

    def _ensure_release(self) -> None:
        if self._ensured:
            return
        envv = {**os.environ, "GH_TOKEN": self.token}
        check = subprocess.run(
            ["gh", "release", "view", self.tag, "--repo", self.repo],
            capture_output=True, env=envv,
        )
        if check.returncode != 0:
            subprocess.run(
                ["gh", "release", "create", self.tag, "--repo", self.repo,
                 "--title", f"Assets {self.tag}", "--notes", "Automated media assets."],
                check=True, capture_output=True, env=envv,
            )
        self._ensured = True

    def upload(self, path: Path) -> str:
        self._ensure_release()
        envv = {**os.environ, "GH_TOKEN": self.token}
        subprocess.run(
            ["gh", "release", "upload", self.tag, str(path),
             "--repo", self.repo, "--clobber"],
            check=True, capture_output=True, env=envv,
        )
        url = (
            f"https://github.com/{self.repo}/releases/download/{self.tag}/{path.name}"
        )
        log.info("uploaded %s -> %s", path.name, url)
        return url


class S3Host(AssetHost):
    def __init__(self, bucket: str, prefix: str, base_url: str, endpoint: str | None = None):
        import boto3  # imported lazily so the dep stays optional

        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.base_url = base_url.rstrip("/")
        self.client = boto3.client("s3", endpoint_url=endpoint or None)

    def upload(self, path: Path) -> str:
        key = f"{self.prefix}/{path.name}" if self.prefix else path.name
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.client.upload_file(
            str(path), self.bucket, key,
            ExtraArgs={"ContentType": ctype, "ACL": "public-read"},
        )
        url = f"{self.base_url}/{key}"
        log.info("uploaded %s -> %s", path.name, url)
        return url


def build_host(date: str) -> AssetHost:
    """Pick an adapter from environment configuration."""
    kind = os.environ.get("ASSET_HOST", "github_release")

    if kind == "github_release":
        repo = os.environ.get("GITHUB_REPOSITORY")
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if not repo or not token:
            raise RuntimeError(
                "ASSET_HOST=github_release needs GITHUB_REPOSITORY and GH_TOKEN. "
                "Both are provided automatically inside GitHub Actions."
            )
        return GitHubReleaseHost(repo, f"assets-{date}", token)

    if kind == "s3":
        return S3Host(
            bucket=os.environ["S3_BUCKET"],
            prefix=os.environ.get("S3_PREFIX", f"aidaily/{date}"),
            base_url=os.environ["ASSET_BASE_URL"],
            endpoint=os.environ.get("S3_ENDPOINT"),
        )

    raise RuntimeError(f"Unknown ASSET_HOST={kind!r}. Use 'github_release' or 's3'.")


def verify_public(url: str, timeout: int = 15) -> bool:
    """Instagram will silently fail on an unreachable URL - check first."""
    try:
        r = requests.head(url, timeout=timeout, allow_redirects=True)
        return r.status_code < 400
    except requests.RequestException:
        return False
