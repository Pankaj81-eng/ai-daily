"""Stage 3 - turn verified stories into publishable copy.

Two rules govern this module.

GROUNDING: the model may only compress what the feed already gave it. It has
no other knowledge available for this task, and must omit rather than guess.

PLAIN LANGUAGE: the audience runs from AI engineers to people who are simply
curious about AI. Copy has to land for a QA engineer and a non-specialist on
the same read, in a carousel someone swipes through in twenty seconds. That
means short sentences, no jargon that isn't unavoidable, and impact before
mechanism.

If ANTHROPIC_API_KEY is absent the module falls back to extractive
summarisation so `--dry-run` still produces a full, inspectable edition.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime

from .config import env
from .models import Edition, Story

log = logging.getLogger(__name__)

SYSTEM = """You write the daily AI brief for TechTales Engineering, an
Instagram and YouTube channel whose promise is "AI engineering made simple".

AUDIENCE: AI engineers, software and QA engineers, technical professionals,
and curious non-experts - all reading the same three slides. Write so the
engineer learns something and the non-expert is never lost. Assume no
familiarity with model names, benchmarks or research terminology.

ABSOLUTE RULES, in priority order:
1. GROUNDING OF FACTS. Every FACT must be directly supported by the source
   text given for that story. Never invent figures, dates, version numbers,
   pricing, availability, benchmark results, customer names or company
   relationships. If it is not in the text, it does not go on the slide.

   Consequences are the exception, and the reason this brief exists. You may
   state what a stated fact plainly implies for the reader, provided the
   implication follows from the fact and is hedged honestly.
     Source says "one third of the cost" -> "Could cut AI search costs" is fine.
     Source says "one third of the cost" -> "Now the cheapest option available"
     is NOT fine; that is a new factual claim about the market.
   Hedge with "could", "may", "makes it easier to". Never hedge a fact that
   the source states outright.
2. OMIT RATHER THAN GUESS. If the source is thin, write something plainer.
   Never fill a gap with plausible detail.
3. PLAIN LANGUAGE. Explain the impact, not the architecture. Replace jargon
   with ordinary words wherever possible. If a technical term is unavoidable,
   make its meaning clear from context in the same sentence.
   Bad:  "Sparse MoE routing improves throughput at longer context lengths."
   Good: "The model handles much longer documents without slowing down."
4. NO HYPE. Never use "revolutionary", "game-changing", "breakthrough",
   "insane", "breaking", or exclamation marks. State what happened.
5. PRESERVE UNCERTAINTY. If the source hedges, you hedge. Never upgrade a
   possibility into a fact.

HEADLINES: HEADLINE_WORDS words maximum, ideally six. Active voice. It should
read like an Instagram news headline, not a company press release.

Banned in headlines unless genuinely unavoidable: announces, introduces,
unveils, next-generation, cutting-edge, state-of-the-art, industry-leading,
seamlessly, revolutionary, powerful, robust, our, we, and any product codename
the reader will not recognise. Prefer short plain verbs: launches, releases,
opens, adds, cuts, buys, blocks, open-sources.

NEVER reuse the publisher's headline. Company blogs write from their own point
of view ("Announcing our next-generation inference platform", "Introducing
Project X", "Meet the new..."), which tells a reader nothing. Always rewrite
into the third person, naming the company and saying what actually happened.

   BAD:  "Announcing our next-generation inference platform"
   GOOD: "Nvidia launches faster AI infrastructure"

   BAD:  "Introducing a faster, cheaper embedding model for retrieval"
   GOOD: "OpenAI releases cheaper embedding model"

   BAD:  "Open-weights model family released with permissive licence"
   GOOD: "Hugging Face open-sources model family"

   BAD:  "NVIDIA: next-generation inference platform"
   GOOD: "NVIDIA launches new inference platform"

   BAD:  "OpenAI: faster, cheaper embedding model"
   GOOD: "OpenAI releases cheaper embeddings"

Structure: WHO did WHAT, and where possible why it matters. Never open with
"Announcing", "Introducing", "Meet", "We", "Our", or a product codename the
reader has never heard of. Prefer plain verbs: launches, releases, adds,
opens, cuts, blocks, buys.

TEASERS: 3-5 words, for the cover slide. A hook, not a summary - enough to
make someone swipe, not enough to make reading the slide pointless.
   "Faster chips from Nvidia"
   "Cheaper OpenAI embeddings"
   "Free open-weight models"

BULLETS: at most MAX_BULLETS per story, one short sentence each,
MAX_BULLET_CHARS characters maximum. Never restate the headline.

The bullets answer "why should I care?". Aim for this shape:
   bullet 1 - the concrete thing that changed
   bullet 2 - who it affects and how
   bullet 3 - the practical consequence

   HEADLINE: "OpenAI releases cheaper embeddings"
   BAD  (marketing echo):
     - "The model supports 8192-token inputs."
     - "It is available today in the API."
     - "It matches the previous generation's retrieval quality."
   GOOD (impact):
     - "Runs at about a third of the previous cost."
     - "Could reduce AI search and retrieval bills."
     - "Makes it cheaper to build document search tools."

Reach for the reader's world - cost, speed, effort, what becomes possible -
rather than the company's feature list. A reader who stops after the bullets
should still feel informed.

WHY IT MATTERS: exactly one sentence per story, 95 characters maximum, plain
English. It is the takeaway a reader repeats to a colleague - the consequence
for someone building software, running a business, or learning AI. It must NOT
restate a bullet; if it could be swapped with a bullet, it is not a takeaway.

   "OpenAI runs GPT-5.6 up to 14x faster"
   -> "AI assistants and voice agents can feel significantly more responsive."

   "NVIDIA launches new inference platform"
   -> "Lower inference costs could make AI applications cheaper to operate."

   "Hugging Face open-sources model family"
   -> "Developers can experiment with advanced models without proprietary APIs."

Bullets are third person, always. Source text written by a company about
itself says "we" and "our"; your version names the company or uses "the".
   BAD:  "We are releasing a model that matches our previous quality."
   GOOD: "The new model matches the previous version's quality."

Return ONLY valid JSON, no markdown fence:
{
  "cover_subtitle": "max 42 chars, e.g. '3 AI stories that matter today'",
  "intro_line": "spoken opening for the video, about 14 words",
  "stories": [
    {"headline": "max HEADLINE_WORDS words, third person, never the publisher's own wording",
     "teaser": "3-5 word hook for the cover slide",
     "bullets": ["sentence", "sentence", "sentence"],
     "why_it_matters": "ONE sentence, max 95 chars, the takeaway - never repeats a bullet",
     "script_line": "spoken narration for THIS story only, about SEG_WORDS words"}
  ],
  "matters_professionals": "one sentence, max 105 chars, what today's news changes for someone building or testing software",
  "matters_businesses": "one sentence, max 105 chars, what it changes for companies",
  "matters_learners": "one sentence, max 105 chars, what someone learning AI should take from it",
  "caption": "Instagram caption. A one-line summary, then the three headlines as bullets, then a short question inviting replies, then 8-12 relevant hashtags including #TechTales",
  "yt_title": "max 80 chars",
  "yt_description": "one-line summary, then each story's source URL on its own line"
}
The "stories" array must have exactly the same number of entries, in the same
order, as the stories given to you. The three "matters_" sentences describe
today's stories collectively, not one each."""


# Used only when no model is available. Deliberately generic-but-true per
# category: a heuristic cannot infer a specific consequence, and inventing one
# would break the grounding rule the whole project rests on.
# Several variants per category, picked by slide position, so two stories in
# the same category never show an identical takeaway.
_FALLBACK_WHY: dict[str, list[str]] = {
    "model_release": [
        "A new option to weigh up before committing further to your current model.",
        "More competition at this tier usually means lower prices for everyone.",
        "Worth benchmarking against whatever you run in production today.",
    ],
    "product_launch": [
        "Could change what you can build without extra engineering work.",
        "One less thing you would otherwise have to build yourself.",
        "Changes the shortlist if you are picking tools this quarter.",
    ],
    "tool_release": [
        "Another tool to reach for before writing something yourself.",
        "Could take a chunk of glue code out of your next project.",
    ],
    "regulation": [
        "Rules like this shape what you are allowed to ship, and where.",
        "Compliance work that lands on product teams, not just legal.",
    ],
    "business": [
        "Money moving here signals where the tooling will follow.",
        "A hint about which platforms will still be around to build on.",
    ],
    "research": [
        "An early signal of what production systems may look like next year.",
        "Not shippable yet, but worth knowing before it reaches products.",
    ],
}
_FALLBACK_WHY_DEFAULT = "Worth tracking if you build with or buy AI tools."


def _fallback_why(category: str, index: int) -> str:
    options = _FALLBACK_WHY.get(category)
    if not options:
        return _FALLBACK_WHY_DEFAULT
    return options[index % len(options)]


def _story_block(idx: int, story: Story) -> str:
    return (
        f"--- STORY {idx + 1} ---\n"
        f"Category: {story.category}\n"
        f"Primary source: {story.lead.source_name} (tier {story.best_tier})\n"
        f"All sources: {', '.join(story.sources)}\n"
        f"URL: {story.link}\n"
        f"Headline as published: {story.title}\n"
        f"Source text: {story.lead.summary or '(none provided by feed)'}\n"
    )


def _trim_words(text: str, limit: int) -> str:
    words = text.split()
    return text if len(words) <= limit else " ".join(words[:limit])


# Company blogs write headlines from their own point of view. These patterns
# turn that first-person framing into third person and name the company, which
# is the single biggest readability win available without a model call.
_PR_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^announcing\s+(?:our\s+|the\s+|a\s+|an\s+)?(?:new\s+)?", re.I), "launches "),
    (re.compile(r"^introducing\s+(?:our\s+|the\s+|a\s+|an\s+)?(?:new\s+)?", re.I), "launches "),
    (re.compile(r"^meet\s+(?:our\s+|the\s+|a\s+)?(?:new\s+)?", re.I), "launches "),
    (re.compile(r"^say\s+hello\s+to\s+(?:our\s+|the\s+|a\s+)?", re.I), "launches "),
    (re.compile(r"^we(?:'re|\s+are)\s+(?:excited\s+|thrilled\s+|proud\s+)?"
                r"(?:to\s+)?(?:announce|introduce|launch|release|share|unveil)"
                r"(?:ing)?\s+(?:that\s+|our\s+|the\s+|a\s+|an\s+)?(?:new\s+)?", re.I), "launches "),
    (re.compile(r"^(?:our|the)\s+new\s+", re.I), "launches new "),
    (re.compile(r"^now\s+available[:,]?\s+", re.I), "releases "),
]

# Passive constructions that read as press copy: "X released with Y" reads
# better as "<Company> releases X with Y".
_PASSIVE = re.compile(
    r"^(?P<what>.+?)\s+(?:has\s+been\s+|have\s+been\s+|is\s+|are\s+|was\s+|were\s+)?"
    r"(?P<verb>released|launched|announced|unveiled|introduced|published)\s*(?P<rest>.*)$",
    re.I,
)
_VERB_ACTIVE = {
    "released": "releases", "launched": "launches", "announced": "announces",
    "unveiled": "unveils", "introduced": "launches", "published": "publishes",
}


# Corporate vocabulary -> plain English. Applied longest-first so multi-word
# phrases win over their constituent words.
_PLAIN: dict[str, str] = {
    "next-generation": "new",
    "next generation": "new",
    "state-of-the-art": "leading",
    "state of the art": "leading",
    "cutting-edge": "new",
    "industry-leading": "",
    "best-in-class": "",
    "enterprise-grade": "business",
    "end-to-end": "",
    "seamlessly": "",
    "revolutionary": "",
    "groundbreaking": "",
    "generally available": "now available",
    "general availability": "general release",
    "open-weights": "open-source",
    "open weights": "open-source",
    "open-weight": "open-source",
    "embedding model": "embeddings",
    "embedding models": "embeddings",
    "large language model": "AI model",
    "large language models": "AI models",
    "leverages": "uses",
    "leveraging": "using",
    "utilises": "uses",
    "utilizes": "uses",
    "capabilities": "features",
    "solution": "tool",
    "offering": "product",
}

# Prepositional tails that can be dropped without changing the news.
_TAIL_PREPS = {
    "with", "for", "under", "across", "through", "including", "featuring",
    "using", "via", "from", "at", "on", "in", "to", "and", "as",
}


def plainify(text: str) -> str:
    """Swap corporate vocabulary for plain words."""
    out = text
    for phrase in sorted(_PLAIN, key=len, reverse=True):
        out = re.sub(rf"\b{re.escape(phrase)}\b", _PLAIN[phrase], out, flags=re.I)
    return " ".join(out.split())


def _trim_to_news_length(text: str, max_words: int) -> str:
    """Cap the length, cutting at a clause boundary rather than mid-phrase.

    "Hugging Face open-sources model family with permissive licence" becomes
    "Hugging Face open-sources model family", not "...family with permissive".
    """
    words = text.split()
    if len(words) > max_words:
        words = words[:max_words]
    # Drop a dangling prepositional phrase left by the cut.
    for i in range(len(words) - 1, 0, -1):
        if words[i].lower().strip(",") in _TAIL_PREPS:
            if i >= 3:                       # keep at least a short headline
                words = words[:i]
            break
    while words and words[-1].lower().strip(",") in _TAIL_PREPS | _TRAILING_JUNK:
        words.pop()
    return " ".join(words).rstrip(" ,.:;-")


def humanize_headline(title: str, company: str, max_words: int = 8) -> str:
    """Rewrite a publisher's headline into plain third-person English.

    A heuristic stand-in for the model, used by the extractive fallback so a
    run without an API key still produces readable slides rather than
    "Announcing our next-generation inference platform".
    """
    text = " ".join(title.split()).rstrip(" .")
    if not company:
        return _trim_to_news_length(plainify(text), max_words)

    rewritten = None
    for pattern, verb in _PR_PATTERNS:
        if pattern.match(text):
            rewritten = f"{company} {verb}{pattern.sub('', text, count=1)}".strip()
            break

    if rewritten is None and text.lower().startswith(company.lower()):
        rewritten = text                      # already third person

    if rewritten is None:
        m = _PASSIVE.match(text)
        if m:
            what = m.group("what").strip()
            verb = _VERB_ACTIVE.get(m.group("verb").lower(), "releases")
            rest = m.group("rest").strip()
            # Skip when "what" is really a clause rather than a thing.
            if 0 < len(what.split()) <= 7:
                rewritten = " ".join(
                    f"{company} {verb} {what} {rest}".split()
                )

    out = plainify(rewritten or text)

    # "releases open-source X" is one verb in plain English: "open-sources X".
    out = re.sub(r"\b(?:releases|launches|publishes)\s+open-source\b",
                 "open-sources", out, flags=re.I)

    return _trim_to_news_length(out, max_words)


# Verbs the headline rewriter puts at the front; the cover hook drops them.
_LEAD_VERBS = {
    "launches", "releases", "announces", "unveils", "publishes", "issues",
    "adds", "opens", "brings", "expands", "details", "cuts", "buys", "blocks",
    "acquires", "raises", "ships", "debuts", "introduces", "open-sources",
    "open-source", "unveil", "rolls",
}
_TRAILING_JUNK = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "at", "by", "from", "its", "their", "our", "new", "under", "over",
    "after", "before", "into", "about", "across", "through", "during",
    "without", "within", "as", "is", "are", "that", "this",
}


def make_teaser(headline: str, company: str, max_words: int = 4) -> str:
    """A short cover hook: the company, then what it did.

    Rendered as "Company: object" because that always scans, whereas trimming
    a headline to N words strands function words ("...inference in the") or
    leaves a bare verb up front ("Launches cheaper model").

    Only used when the model did not supply a teaser of its own.
    """
    words = headline.split()

    # Strip the company name, however many words it runs to. Only prefix
    # "Company:" if the headline actually names that company - otherwise the
    # source is a publisher reporting on someone else, and "TechCrunch: Europe
    # issues guidance" credits entirely the wrong party.
    named = False
    if company:
        co_words = company.split()
        if [w.lower().strip(":,") for w in words[: len(co_words)]] == [
            w.lower() for w in co_words
        ]:
            words = words[len(co_words):]
            named = True

    if named:
        # Strip the leading verb - the hook is about the thing, not the action.
        if words and words[0].lower() in _LEAD_VERBS:
            words = words[1:]
        while words and words[0].lower() in _TRAILING_JUNK:
            words = words[1:]
        words = words[:max_words]
    else:
        words = words[: max_words + 2]

    while words and words[-1].lower() in _TRAILING_JUNK:
        words.pop()

    # Casing is left exactly as written: lowercasing here turns "Claude" into
    # "claude" and "Europe" into "europe".
    phrase = " ".join(words).rstrip(" ,.:;-")
    if not phrase:
        return headline
    return f"{company}: {phrase}" if named else phrase


_PERSON_SUBS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bwe(?:'re|\s+are)\b", re.I), "{co} is"),
    (re.compile(r"\bwe(?:'ve|\s+have)\b", re.I), "{co} has"),
    (re.compile(r"\bwe(?:'ll|\s+will)\b", re.I), "{co} will"),
    (re.compile(r"\bwe\b", re.I), "{co}"),
    (re.compile(r"\bour\b"), "its"),
    (re.compile(r"\bOur\b"), "Its"),
    (re.compile(r"\bours\b", re.I), "its"),
]


def depersonalize(text: str, company: str) -> str:
    """Turn a company's first-person prose into third person.

    Feed summaries are written by the company about itself ("We are releasing
    ...", "our new accelerator"). Copied onto a slide verbatim that reads as
    an advert rather than a news brief. Used by the extractive fallback; the
    model is instructed to do this itself.
    """
    if not text or not company:
        return text
    out = text
    for pattern, repl in _PERSON_SUBS:
        out = pattern.sub(repl.replace("{co}", company), out)
    return out[:1].upper() + out[1:] if out else out


def _clip(text: str, limit: int) -> str:
    """Character cap that never cuts a word in half.

    This is a safety net under the model's own length instruction. A hard
    slice produces copy like "...quality of our pr", which is worse than a
    slightly shorter sentence, so back up to the last word boundary.
    """
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return (cut or text[:limit].rstrip()) + "…"


def _fallback(stories: list[Story], settings: dict, date: str) -> Edition:
    """Extractive copy, used when no API key is configured."""
    cfg = settings["summarize"]
    for idx, s in enumerate(stories):
        s.headline = _trim_words(
            humanize_headline(s.title, s.source_label), cfg["max_headline_words"]
        ).rstrip(" .,-:")
        s.teaser = make_teaser(s.headline, s.source_label)
        sentences = [
            x.strip() for x in re.split(r"(?<=[.!?])\s+", s.lead.summary or s.title)
            if x.strip()
        ]
        s.bullets = [
            _clip(depersonalize(x, s.source_label), cfg["max_bullet_chars"])
            for x in sentences[: cfg["max_bullets"]]
        ]
        s.body = " ".join(s.bullets)
        s.script_line = f"{s.headline}. {s.body}"
        # No model available: name the concrete consequence we can defend
        # from the category alone, rather than inventing an impact claim.
        s.why_it_matters = _fallback_why(s.category, idx)

    return Edition(
        date=date,
        stories=stories,
        intro="Today in AI",
        outro=f"{len(stories)} AI stories that matter today",
        intro_line=f"Here are today's {len(stories)} AI stories.",
        matters_professionals="New tools and models change what you can ship this quarter.",
        matters_businesses="Capability and cost curves keep moving; plans need revisiting.",
        matters_learners="Follow the primary sources, not the commentary around them.",
        caption="\n".join(f"- {s.headline} ({s.source_label})" for s in stories),
        yt_title=f"AI News - {date}",
        yt_description="\n".join(f"{s.headline}: {s.link}" for s in stories),
    )


def summarize(stories: list[Story], settings: dict, date: str | None = None) -> Edition:
    date = date or datetime.now().strftime("%Y-%m-%d")
    cfg = settings["summarize"]

    api_key = env("ANTHROPIC_API_KEY")
    if not api_key:
        log.warning("ANTHROPIC_API_KEY not set - using extractive fallback copy")
        return _fallback(stories, settings, date)

    import anthropic

    seg_words = max(12, cfg["script_target_words"] // max(1, len(stories) + 1))
    system = (
        SYSTEM.replace("HEADLINE_WORDS", str(cfg["max_headline_words"]))
        .replace("MAX_BULLETS", str(cfg["max_bullets"]))
        .replace("MAX_BULLET_CHARS", str(cfg["max_bullet_chars"]))
        .replace("SEG_WORDS", str(seg_words))
    )
    user = "\n".join(_story_block(i, s) for i, s in enumerate(stories))

    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=cfg["model"], max_tokens=3000, system=system,
        messages=[{"role": "user", "content": user}],
    )
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", resp.content[0].text.strip())

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.error("model returned non-JSON, falling back to extractive copy")
        return _fallback(stories, settings, date)

    written = data.get("stories", [])
    if len(written) != len(stories):
        log.warning("model returned %d stories for %d inputs", len(written), len(stories))

    for idx, (story, w) in enumerate(zip(stories, written)):
        story.headline = _trim_words(
            w.get("headline") or humanize_headline(story.title, story.source_label),
            cfg["max_headline_words"],
        ).rstrip(" .,-:")
        story.teaser = (
            w.get("teaser") or make_teaser(story.headline, story.source_label)
        ).rstrip(" .,-:")
        bullets = [b.strip() for b in (w.get("bullets") or []) if b and b.strip()]
        story.bullets = [
            _clip(b, cfg["max_bullet_chars"]) for b in bullets[: cfg["max_bullets"]]
        ]
        story.body = " ".join(story.bullets)
        story.script_line = w.get("script_line") or f"{story.headline}. {story.body}"
        story.why_it_matters = _clip(
            w.get("why_it_matters") or _fallback_why(story.category, idx), 95
        )

    # Guarantee every source URL survives into the description.
    desc = data.get("yt_description", "")
    for s in stories:
        if s.link and s.link not in desc:
            desc += f"\n{s.headline}: {s.link}"

    kept = stories[: len(written)] or stories
    return Edition(
        date=date,
        stories=kept,
        intro="Today in AI",
        outro=data.get("cover_subtitle") or f"{len(kept)} AI stories that matter today",
        intro_line=data.get("intro_line", "Here is today's AI news."),
        matters_professionals=_clip(data.get("matters_professionals", ""), 105),
        matters_businesses=_clip(data.get("matters_businesses", ""), 105),
        matters_learners=_clip(data.get("matters_learners", ""), 105),
        caption=data.get("caption", ""),
        yt_title=data.get("yt_title", f"AI News - {date}"),
        yt_description=desc,
    )
