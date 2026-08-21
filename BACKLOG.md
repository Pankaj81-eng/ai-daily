# Backlog

Known issues and improvements that aren't blocking the daily post, tracked
here instead of fixed in the moment so they don't get lost. Add to this
whenever something comes up that's worth knowing about but not worth
stopping to fix right then.

When picking one up, move it to a "Done" note at the bottom (or just delete
the line) once it's actually fixed and committed.

## Robustness

- **A failed Telegram video upload crashes the whole approval flow.**
  `approval.send_preview()` sends the video *before* the Publish/Discard
  buttons. If the video upload fails (seen once already — a plain network
  "Connection reset by peer"), the run dies before the buttons ever get
  sent, so a fully-built, review-ready edition never reaches you. Fix:
  wrap the `sendVideo` call in try/except so a video failure logs a warning
  and continues to the buttons instead of crashing.

- **`summarize()` doesn't fall back gracefully on API errors.** It already
  falls back to the free extractive writer when `ANTHROPIC_API_KEY` is
  missing, and when the model returns non-JSON — but if `client.messages
  .create()` itself raises (billing failure, rate limit, network blip),
  the whole run crashes instead of falling back the same way. This is
  exactly what happened today's billing error, both locally and in GitHub
  Actions. Fix: wrap the API call in try/except and fall back to
  `_fallback()` on any `anthropic.APIError`, same pattern already used for
  the JSON-decode-failure case.

## Content quality

- **Model occasionally returns non-JSON** on some inputs (seen on a
  fixtures test run — `model returned non-JSON, falling back to extractive
  copy`). The built-in fallback caught it fine, so nothing broke, but
  worth understanding why it happens (extra prose wrapping around the JSON
  block?) if it starts happening often.

## Deferred features

- **Phase 3 of the Aug 2026 signal-expansion plan: tier-3 web verification.**
  Original 4-point plan (relax tier-3 sources, broaden scope, allow 2-3
  stories, recalibrate audience) was built as 3 phases - Phase 1 (scope +
  audience) and Phase 2 (multi-story, 0-3 stories) both shipped and are
  live. Phase 3 - letting a tier-3 source (Ben's Bites/TLDR/Rundown) publish
  alone if a live web search independently confirms the claim, via a new
  Gemini API key kept separate from the Anthropic editorial key - was
  deliberately held back. Reasoning: Phases 1+2 address the actual root
  cause (pool visibility + narrow scope + rigid one-story format), and
  TLDR/Rundown/Ben's Bites are professionally curated already - a story
  significant enough to matter almost always also gets tier-1/2 pickup
  within the 48h window anyway. A story that's *only* ever mentioned by one
  curator and nothing else in 48h is a genuine edge case, not the main gap.
  Revisit only if a specific, recurring pattern shows up (a tier-3-only
  story that should have qualified keeps getting missed) - not as a
  default next step. May turn out to never be needed.

- **Make the GitHub repo private (blocked on switching asset hosting off
  GitHub Releases).** Repo is public today because `ASSET_HOST=github_release`
  needs a public repo - GitHub only serves release assets over an
  unauthenticated URL (which Instagram/YouTube's fetch step requires) on
  public repos. The code already has a ready-to-use alternative:
  `ASSET_HOST=s3`, which works with any S3-compatible bucket, including
  Cloudflare R2. Checked R2's actual pricing: 10GB storage + 1M writes +
  10M reads per month free, zero egress fees, forever - at this project's
  real usage (one publish/day at most, a few small images + one video) that
  free tier would take well over a year to approach even without ever
  deleting old assets. Not a cost concern if picked up. Deliberately not
  done yet - not because of any blocker, just not important enough right
  now. To do it: create an R2 bucket + API credentials, add them as new
  secrets, switch `ASSET_HOST` to `s3` in `daily.yml`, verify a real
  publish still works, then flip the repo to Private on GitHub.

## Maintenance

- **GitHub Actions using deprecated Node 20** — `actions/checkout@v4`,
  `actions/setup-python@v5`, `actions/upload-artifact@v4` are being forced
  onto Node 24 with a deprecation warning. Not broken yet; bump to their
  latest major versions when convenient.

## Expiry reminders

- **Instagram long-lived token expires ~60 days from generation** (mid-to-
  late Sept 2026 based on when it was issued). Refresh before then or
  publishing starts failing.
- **YouTube refresh token expires every ~7 days.** The Google Cloud OAuth
  app (`ai-daily`) is in Testing status, not verified/published, and
  Google auto-expires refresh tokens issued by unverified apps after 7
  days regardless of anything else. Live and working as of 21 Aug 2026,
  but expect `youtube_error` to start showing up in results.json again
  about a week later unless re-authenticated. To refresh: rerun
  `get_token.py` locally (regenerate it from SETUP.md §8 if it's been
  deleted) and update the `YT_REFRESH_TOKEN` GitHub secret. Submitting the
  app for Google's verification would make this permanent instead of
  weekly - a real option if this becomes annoying, deliberately not done
  yet (see chat history around 19-21 Aug 2026 for the trade-off
  discussion).

## Pending — not started

- (none currently)

## Design / polish (low priority)

- Cover slide date visibility — **done**, fixed 15 Aug 2026 (moved from
  small top-right text to a prominent line below "Daily AI Brief").
