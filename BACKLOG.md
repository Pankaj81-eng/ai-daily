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

- **arXiv papers get misclassified as `model_release`** (the top editorial
  priority) instead of `research`, because the category classifier picks
  up keywords like "model" inside paper abstracts. This is why arXiv kept
  winning story selection over working press feeds. Only stopped mattering
  once the Anthropic key was funded (a real model can summarize arXiv
  abstracts properly; the free fallback can't). Worth fixing the
  classifier so arXiv is reliably tagged `research` regardless of its
  abstract's wording.

- **Model occasionally returns non-JSON** on some inputs (seen on a
  fixtures test run — `model returned non-JSON, falling back to extractive
  copy`). The built-in fallback caught it fine, so nothing broke, but
  worth understanding why it happens (extra prose wrapping around the JSON
  block?) if it starts happening often.

## Maintenance

- **Dead RSS feeds** — these return 404/410 every run and need fixing or
  removing from `config/sources.yaml`: Microsoft AI Blog, Anthropic News,
  Mistral AI News, Meta AI Blog, Reuters Technology.

- **GitHub Actions using deprecated Node 20** — `actions/checkout@v4`,
  `actions/setup-python@v5`, `actions/upload-artifact@v4` are being forced
  onto Node 24 with a deprecation warning. Not broken yet; bump to their
  latest major versions when convenient.

## Expiry reminders

- **Instagram long-lived token expires ~60 days from generation** (mid-to-
  late Sept 2026 based on when it was issued). Refresh before then or
  publishing starts failing.
- **GH_TOKEN (fine-grained, `ai-daily-publish-v3`) expires 13 Nov 2026.**
  Regenerate with the same Contents + Actions permissions before then.

## Design / polish (low priority)

- Cover slide date visibility — **done**, fixed 15 Aug 2026 (moved from
  small top-right text to a prominent line below "Daily AI Brief").
