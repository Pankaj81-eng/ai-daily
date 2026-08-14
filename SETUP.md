# Setup

Work through this in order. Stages 1–3 get you a running pipeline you can look
at; stages 4–7 connect it to your accounts.

Budget about 2 hours for the first pass. Instagram and YouTube onboarding is
genuinely fiddly — that's platform bureaucracy, not this repo.

---

## 1. Run it locally with no accounts at all

```bash
git clone <your-repo> && cd ai-daily
pip install -r requirements.txt
playwright install chromium

# macOS
brew install ffmpeg espeak-ng
# Ubuntu/Debian
sudo apt install ffmpeg espeak-ng

python -m aidaily.cli run --dry-run --fixtures
open out/*/slide_00.png
```

If you see slides, everything structural works. `--fixtures` uses bundled
sample stories, so this needs no network and no keys.

## 2. Point it at real news

```bash
python -m aidaily.cli sources
```

Every feed should report recent items. **Expect one or two to be wrong** —
publishers change RSS URLs regularly. Fix or delete anything reported EMPTY in
`config/sources.yaml`, then:

```bash
python -m aidaily.cli run --dry-run
```

Read `out/<date>/edition.json`. Every story lists its tier, its corroborating
sources and its URLs. This is the moment to check you agree with what survived
verification — and to run `-v` to see what was rejected and why.

## 3. Brand it

Edit `config/settings.yaml`:

```yaml
brand:
  handle: "@your_actual_handle"
  name: "YOUR BRAND"
  accent: "#5B8CFF"       # your colour
```

Re-run with `--fixtures` and look at the PNGs. Iterate until you like it. Do
this *before* wiring up publishing — it's much faster without the network in
the loop.

## 4. Anthropic API key (writing quality)

Get one at <https://console.anthropic.com>. Without it the pipeline falls back
to extractive summaries, which are accurate but flat.

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Cost is roughly one call per day. Pennies per month.

## 5. Telegram approval bot

The cheapest reliable approval channel — renders media on your phone, gives
real tap buttons, needs no server.

1. Message [@BotFather](https://t.me/BotFather), send `/newbot`, follow the
   prompts. Copy the token → `TELEGRAM_BOT_TOKEN`.
2. Send your new bot any message (it can't message you first).
3. Get your chat id:
   ```bash
   curl "https://api.telegram.org/bot<TOKEN>/getUpdates" | grep -o '"id":[0-9-]*' | head -1
   ```
   → `TELEGRAM_CHAT_ID`.

Test the whole loop without publishing anything:

```bash
python -m aidaily.cli run --fixtures      # sends preview, waits for your tap
```

Tap **Discard** — nothing publishes, but you've confirmed the gate works.

## 6. Instagram

This is the most involved step. Requirements are non-negotiable, set by Meta.

**Your account must be a Business or Creator account linked to a Facebook
Page.** Personal Instagram accounts cannot publish through any API. Convert in
the Instagram app: Settings → Account type and tools → Switch to professional.

1. Create an app at <https://developers.facebook.com/apps> → type **Business**.
2. Add the **Instagram** product.
3. Request these permissions:
   - `instagram_business_basic`
   - `instagram_business_content_publish`
4. Complete **Page Publishing Authorization (PPA)** on the linked Facebook
   Page. Publishing fails without it.
5. Generate a **long-lived access token** → `IG_ACCESS_TOKEN`.
6. Get your Instagram professional account ID (a number, not your handle) →
   `IG_USER_ID`.

Verify before trusting it:

```bash
curl "https://graph.instagram.com/v21.0/$IG_USER_ID/content_publishing_limit?access_token=$IG_ACCESS_TOKEN"
```

A quota number back means you're wired up correctly.

**Things that will bite you:**

- Long-lived tokens expire after **60 days**. Refresh them, or the job starts
  failing silently two months in. Put a calendar reminder at day 50.
- Instagram **fetches** your media from a public URL — it does not accept
  uploads for images. That's what stage 7 is for.
- API publishing is capped at 100 posts per rolling 24 hours. A carousel counts
  as one.
- All carousel slides get cropped to the aspect ratio of the **first** slide.
  Every slide here is rendered at an identical 1080×1350, so this is handled.

## 7. Public asset hosting

Because of the fetch-not-upload constraint above, rendered media must be
reachable on the open internet for a few minutes.

**Option A — GitHub Releases (default).** Free, no extra account. Requires the
repo to be **public**. Inside GitHub Actions it works with zero configuration.

```bash
ASSET_HOST=github_release
```

**Option B — S3-compatible.** Use this if you want the repo private.
Cloudflare R2 has a generous free tier.

```bash
ASSET_HOST=s3
S3_BUCKET=my-bucket
S3_ENDPOINT=https://<account>.r2.cloudflarestorage.com
ASSET_BASE_URL=https://assets.yourdomain.com
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
pip install boto3
```

## 8. YouTube

1. Create a project at <https://console.cloud.google.com>.
2. Enable **YouTube Data API v3**.
3. Create an **OAuth 2.0 Client ID** of type *Desktop app* → `YT_CLIENT_ID`,
   `YT_CLIENT_SECRET`.
4. Get a refresh token once, locally:

```python
# save as get_token.py, run once, then delete
from google_auth_oauthlib.flow import InstalledAppFlow

flow = InstalledAppFlow.from_client_config(
    {"installed": {
        "client_id": "YOUR_CLIENT_ID",
        "client_secret": "YOUR_CLIENT_SECRET",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }},
    scopes=["https://www.googleapis.com/auth/youtube.upload"],
)
creds = flow.run_local_server(port=8080)
print("YT_REFRESH_TOKEN =", creds.refresh_token)
```

**Read this before you wonder why nothing is public:** a Google Cloud project
that has not passed YouTube's **API compliance audit** has all its uploads
**forced to private**, no matter what privacy setting you request. This is
normal and expected for a new project. The pipeline detects it and logs a
clear warning rather than failing quietly.

Your options: request an audit at
<https://support.google.com/youtube/contact/yt_api_form> (takes a few weeks),
or leave uploads private and flip them to public by hand each morning — which
is a 10-second job and pairs fine with the approval gate.

Unaudited projects are also limited to a handful of uploads per day. One a day
is well within that.

## 9. Deploy to GitHub Actions

1. Push the repo (**public** if using `github_release` hosting).
2. Settings → Secrets and variables → Actions → add:

   | Secret | From |
   |---|---|
   | `ANTHROPIC_API_KEY` | step 4 |
   | `TELEGRAM_BOT_TOKEN` | step 5 |
   | `TELEGRAM_CHAT_ID` | step 5 |
   | `IG_USER_ID` | step 6 |
   | `IG_ACCESS_TOKEN` | step 6 |
   | `YT_CLIENT_ID` | step 8 |
   | `YT_CLIENT_SECRET` | step 8 |
   | `YT_REFRESH_TOKEN` | step 8 |

3. Actions tab → **AI Daily** → *Run workflow* → tick **dry_run**. Confirm it
   builds and check the uploaded artifacts.
4. Run it again without dry_run. You should get a Telegram preview.
5. Adjust the cron in `.github/workflows/daily.yml`. It's UTC, and GitHub's
   scheduler drifts 5–30 minutes under load — set it earlier than your target
   post time.

   For 7:00 AM IST: `30 1 * * *`. For 7:00 AM UK summer time: `0 6 * * *`.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `sources` shows many EMPTY | Feed URLs moved, or your network blocks them. Fix `config/sources.yaml`. |
| "Nothing new passed verification" | Genuinely quiet news day, or `state/seen.json` already has everything. Working as intended. |
| Instagram: "media URL not reachable" | Repo is private with `github_release` hosting, or the release upload failed. |
| Instagram 400 on publish | PPA not completed, or token expired (60-day limit). |
| YouTube uploads land private | Compliance audit not passed. Expected — see step 8. |
| Video render fails | ffmpeg missing, or edge-tts is down and espeak-ng isn't installed. |
| Same story twice in one carousel | Raise `verify.cluster_similarity` sensitivity by *lowering* the value, and open an issue with the two headlines. |
