# TechTales Engineering — AI Daily

An automated morning AI brief for [@techtalesengineering](https://www.instagram.com/techtalesengineering):
a six-slide Instagram carousel covering the three AI stories that matter,
readable in under twenty seconds, with a human approval step and a verification
layer that refuses to post anything it can't attribute.

```
feeds ─► cluster ─► VERIFY ─► rank ─► images ─► write ─► render ─► approve ─► publish
                      │         │        │        │         │          │
            tier rules,    editorial  official  plain    6 slides   Telegram
            citation graph, priority   og:image language  + short   tap to
            rumour+clickbait                                        confirm
```

## The carousel

| # | Slide | Contents |
|---|---|---|
| 1 | Cover | "Today in AI", the date, and three short teaser hooks |
| 2–4 | Story | Large relevant image, news headline (≤8 words), up to 3 key facts, a one-line **Why it matters**, visible source |
| 5 | Why it matters | One line each for builders, businesses and learners |
| 6 | Follow | "Trusted AI updates in under 20 seconds" |

Every slide carries the TechTales mark **and** `@techtalesengineering`, so a
single screenshot re-shared out of context still carries attribution.

## Headlines are rewritten, never reused

Company blogs write from their own point of view, which tells a reader
nothing. Publisher headlines are always rewritten into third person naming who
did what:

| Published as | Posted as |
|---|---|
| "Announcing our next-generation inference platform" | "NVIDIA launches new inference platform" |
| "Introducing a faster, cheaper embedding model" | "OpenAI launches faster, cheaper embeddings" |
| "We are excited to announce our new agent framework" | "Google DeepMind launches agent framework" |
| "Open-weights model family released with permissive licence" | "Hugging Face open-sources model family" |

Headlines are capped at 8 words, run through a corporate-vocabulary filter
("next-generation" becomes "new", "open-weights" becomes "open-source"), and
trimmed at clause boundaries so they never end on a dangling preposition.

Bullets answer **"why should I care?"** rather than echoing the announcement:
what changed, who it affects, what it costs or saves. Facts stay strictly
grounded in the source, but stating what a fact *implies* for the reader is
allowed and expected — hedged honestly ("could cut search costs"), never
inventing a new factual claim.

The same applies to bullets: source text saying "we" and "our" is converted to
third person, so a slide reads as news rather than as an advert.

The model does this from the prompt. `aidaily/summarize.py` also implements it
as a rule-based rewriter (`humanize_headline`, `depersonalize`) so a run
**without** an API key still produces readable slides instead of press copy.

## The part that matters: verification

Anyone can pipe an RSS feed into a template. The reason this repo exists is
everything in `aidaily/verify.py`, which decides what is allowed to carry your
name.

| Tier | What it is | Publishable? |
|---|---|---|
| 1 | The organisation announcing its own work, a regulator, arXiv | Yes, alone — the primary source *is* the evidence |
| 2 | Established newsrooms with corrections policies | Only with a second independent report, **or** an outbound link to a tier-1 primary |
| 3 | Aggregators, forums | Never alone, under any circumstances |

On top of the tiers:

- **Rumours and leaks are dropped, not downranked.** "Reportedly", "sources
  say", "leaked", "allegedly" and friends hard-reject a story — but only at
  tier 2 and 3, because a company announcing its own product never writes
  "reportedly". A genuine primary announcement can never be suppressed by this
  rule.
- **Clickbait is dropped at every tier**, including tier 1. "This changes
  everything" is not the brand being built here.
- **Citation-graph clustering.** If The Verge writes about an Nvidia
  announcement and links to `blogs.nvidia.com`, those are one story, not two.
  Checked before headline similarity because it's far stronger evidence — and
  it's what stops one event eating two of your three slides.
- **Editorial priority.** Stories are classified and ranked in the briefed
  order: model releases > product launches > tool releases > regulation >
  business > research. Keyword matching is whole-word, so "the AI Act" counts
  as regulation but "real impact" does not.
- **One story per source.** Three slides from one company's press day isn't a
  brief, so at three stories the selector allows one per source.
- **Grounded copywriting.** The model gets only the fetched source text and is
  forbidden from adding figures, dates or context that aren't in front of it.
  It must omit rather than guess, and must preserve the source's own hedging.
- **Auditable rejections.** Every dropped story records *why*. Run with `-v`.
- **Source on every slide**, plus the primary URL in the caption and video
  description.

None of this makes the output infallible, which is exactly why the Telegram
approval gate is on by default.

## Images

The carousel is image-led, so `aidaily/images.py` works down this hierarchy:

1. **The article's own imagery** — the publisher's nominated share image
   first, then the article's hero and in-body images, largest first. Several
   candidates are collected per article and tried in turn, because the first
   one often fails on a hotlink block or an expired CDN path.
2. **The company's own hero image**, from that company's homepage.
3. **The company's logo** on a branded panel.
4. **A generated branded panel** naming the company, so a slide is never
   broken. Last resort only.

Steps 2–4 use the company the story is **about**, not the outlet that reported
it — `config/companies.yaml` maps ~30 AI companies and their products
(ChatGPT → OpenAI, Blackwell → Nvidia, Claude → Anthropic) to brand domains.
Without that, a TechCrunch article about Nvidia would show the *TechCrunch*
logo: correct attribution, wrong picture. Add your own entries freely.

Generic house share-cards are rejected on the way through: many sites serve
one identical og:image for every article, which is technically valid but shows
nothing about the story. Those are detected by comparing against the domain's
homepage card, and fall through to the logo panel instead — visual relevance
beats decoration.

Story copy is auto-fitted: after layout, the renderer measures the text block
and steps the type down (never below 70%) until it fits. The image panel keeps
its size, so a long headline plus three facts plus the takeaway can never push
content under the footer.

Any aspect ratio lands cleanly: images fill the panel edge to edge when that
costs less than 25% of the frame, and otherwise sit centred on a blurred,
darkened copy of themselves rather than being hard-cropped through the subject.
Set `images.mode` to `official` to skip stories with no real image, or `logo`
for a uniform look.

## Quick start

```bash
pip install -r requirements.txt
playwright install chromium
sudo apt install ffmpeg espeak-ng          # brew install ffmpeg espeak-ng on macOS

# See the design with sample stories, no network and no keys needed
python -m aidaily.cli run --dry-run --fixtures

# Same thing against real feeds
python -m aidaily.cli run --dry-run

python -m aidaily.cli doctor               # what's configured, what's missing
python -m aidaily.cli sources              # is every feed alive?
python -m pytest tests/ -q                 # verification rules still hold?
```

Output lands in `out/<date>/`: numbered `slide_*.png`, `short.mp4`, and
`edition.json` with the full provenance of every story.

For live publishing, see **[SETUP.md](SETUP.md)** — the Instagram and YouTube
onboarding is the fiddly part, and it's written out step by step.

## Making it yours

| Want to change | Edit |
|---|---|
| **Logo** | replace `assets/logo.png` (square PNG, 512px+) |
| Colours, handles, tagline | `config/settings.yaml` → `brand` |
| Which sources are trusted | `config/sources.yaml` (tier deliberately) |
| How strict verification is | `config/settings.yaml` → `verify` |
| Editorial priority | `verify.category_boost` |
| Number of stories per day | `verify.target_story_count` |
| Image strategy | `images.mode` — `hybrid` / `official` / `logo` |
| How much of the slide is image | `carousel.image_ratio` |
| Turn the video off | `video.enabled: false` |
| Voice / language | `video.tts_voice` (try `en-IN-NeerjaNeural`) |
| Slide layout | `templates/slide.html.j2` — plain HTML/CSS |
| Tone of the writing | the `SYSTEM` prompt in `aidaily/summarize.py` |

### Installing your real logo

`assets/logo.png` currently holds a **vector reconstruction** of the channel
avatar, so the pipeline runs out of the box. To swap in the real export:

```bash
python set_logo.py ~/Downloads/techtales-avatar.png
python set_logo.py --check
```

It accepts any format or shape — a banner, a screenshot, a non-square export —
centre-crops it to a square, resizes to 512×512 and writes `assets/logo.png`.
Every slide picks it up on the next render. If you'd rather do it by hand, just
drop the file at `assets/logo.png`; `logo.jpg`, `.jpeg`, `.webp` and `.svg` are
detected too.

### Why the image is 60% of the slide

Rendered at 0.70, 0.60 and 0.50 against a realistic three-bullet story:

- **0.70** — the headline crowds the footer once it wraps to three lines
- **0.60** — image still dominates, copy sits comfortably ✅
- **0.50** — worse on *both* counts: the shorter panel is proportionally wider,
  so images get letterboxed more often, and the copy no longer fills the space
  it's given

One line to change if you disagree: `carousel.image_ratio`.

Restyling is fast: edit a template, run `--dry-run --fixtures`, look at the
PNGs, repeat. No API keys, no waiting for news.

## Scheduling

`.github/workflows/daily.yml` runs at 06:15 UTC daily. GitHub's scheduler
drifts by 5–30 minutes under load, so set the cron earlier than the time you
actually want to post. You can also trigger it by hand from the Actions tab,
with dry-run and skip-approval toggles.

## Cost

GitHub Actions is free for public repos, and this uses roughly 8–10 minutes of
compute per run plus the approval wait. The only recurring cost is one
Anthropic API call per day — a few cents a month. edge-tts is free.

## Known limits

- **The feed list is a starting point, not a verified set.** Publishers move
  and retire RSS URLs. Run `python -m aidaily.cli sources` before your first
  real run and fix anything reported EMPTY.
- **Instagram fetches media from a public URL**, so `github_release` hosting
  needs a public repo. Use the `s3` adapter (Cloudflare R2 works well) if you
  want the repo private.
- **YouTube forces uploads to private** until your Google Cloud project passes
  the API compliance audit. This is detected and logged rather than failing
  silently. See SETUP.md.
- **Long-lived Instagram tokens expire after 60 days** and need refreshing.
- edge-tts uses an undocumented Microsoft endpoint; `espeak-ng` is wired in as
  an automatic fallback so one bad morning doesn't kill the run.
