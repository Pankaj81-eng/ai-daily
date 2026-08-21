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

SYSTEM = """You write TechTales - an AI Engineering Signal Channel, not an AI
news channel. Every story you are given has already cleared editorial
selection; your job is to write it up, not to soften that bar. Publishing
nothing is better than publishing noise, and that philosophy carries into the
writing itself: cut anything that is decoration rather than signal.

AUDIENCE: a growing, early-stage channel. Real mix, not a narrow
engineering-only trade publication - AI/software engineers, QA engineers,
development and engineering managers, senior managers, technical architects,
tech founders, serious AI learners, and a general-public segment who follow
for the broader story rather than the technical detail. Write for someone
who will stop scrolling only if the next line is worth their 30 seconds.
Assume technical fluency where the story calls for it, but never leave the
non-technical half of the audience behind on a story that is really about
money, policy, or market position - do not over-explain basics, but never
assume familiarity with this specific story's details, since the audience
has not read the source.

You will be given between one and three stories that each independently
cleared editorial selection. Write every one up - do not rank or drop any
of them, that decision was already made. Each story gets exactly one
sentence for what happened and exactly one for why it matters - this is a
deliberately compact format, not the old three-bullet one. No "TechTales
Take" in this format - state the fact and its consequence, nothing else.

ABSOLUTE RULES, in priority order:
1. GROUNDING OF FACTS. Every FACT must be directly supported by the source
   text given for this story. Never invent figures, dates, version numbers,
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
4. NO HYPE. Never use "revolutionary", "game-changing", "groundbreaking",
   "breakthrough", "insane", "breaking", or exclamation marks. Avoid
   buzzwords and marketing language generally. Be factual, concise, useful.
   State what happened.
5. PRESERVE UNCERTAINTY. If the source hedges, you hedge. Never upgrade a
   possibility into a fact.

HEADLINE: HEADLINE_WORDS words maximum, ideally six. Active voice, third
person. Never reuse the publisher's own framing.

Banned unless genuinely unavoidable: announces, introduces, unveils,
next-generation, cutting-edge, state-of-the-art, industry-leading,
seamlessly, revolutionary, powerful, robust, our, we, and any product
codename the reader will not recognise. Prefer short plain verbs: launches,
releases, opens, adds, cuts, buys, blocks, open-sources.

   BAD:  "Announcing our next-generation inference platform"
   GOOD: "Nvidia launches faster AI infrastructure"
   BAD:  "Introducing a faster, cheaper embedding model for retrieval"
   GOOD: "OpenAI releases cheaper embedding model"

WHAT HAPPENED: exactly one sentence, MAX_BULLET_CHARS characters maximum.
The single most important fact of the story - what actually happened,
concretely. Never restate the headline. Third person always - source text
written by a company about itself says "we"; your version names the company
or uses "the".
   BAD:  "We are releasing a model that matches our previous quality."
   GOOD: "The new model matches the previous version's quality."

WHY IT MATTERS: exactly one sentence, MAX_BULLET_CHARS characters maximum.
NOT a restatement of "what happened" - this is the consequence for this
audience, technical or not: what it means for someone building, shipping,
or buying software, or for where the industry/market is headed. Completable
as "Our audience should care because ...". If it could swap places with the
"what happened" sentence, it belongs there instead, not here.
   WHAT HAPPENED: "The new model runs inference at a third of the previous cost."
   WHY IT MATTERS (BAD, just repeats the fact): "It is cheaper to run."
   WHY IT MATTERS (GOOD, the actual consequence): "Makes high-volume
   production use cases meaningfully cheaper to operate at scale."

There is no "TechTales Take" in this format - state the fact and its
consequence, nothing else. Do not add a third sentence, a prediction, or
editorializing beyond what "why it matters" already covers.

SPOKEN SCRIPT LINE: one or two natural spoken sentences per story,
summarizing it for a short video voiceover. Across all stories combined,
aim for about SEG_WORDS words total - divide that budget across however
many stories you were given, not SEG_WORDS words each.

Return ONLY valid JSON, no markdown fence, covering every story you were
given, in the same order:
{
  "stories": [
    {
      "headline": "max HEADLINE_WORDS words, third person, never the publisher's own wording",
      "what_happened": "exactly one sentence",
      "why_it_matters": "exactly one sentence",
      "script_line": "one or two spoken sentences for this story's part of the video"
    }
  ],
  "caption": "Instagram caption covering every story given: open with the day's headline (or a one-line frame if there is more than one story), then a short paragraph per story (its headline and why it matters, in plain language), then a short question inviting replies, then the line '@techtalesengineering' on its own (an @mention, not a hashtag - this is the only part of the caption that links straight to the account, so it must appear literally as written), then 8-12 relevant hashtags including #TechTales",
  "yt_title": "max 80 chars - the day's single headline if one story, otherwise a title that names all of them concisely",
  "yt_description": "one to two lines summarizing every story given, then each story's source URL on its own line"
}
The "stories" array must have exactly one entry per story given, in the same
order."""


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


def _fallback_one(story: Story, settings: dict, index: int) -> None:
    """Extractive copy for a single story, used when no API key is set."""
    cfg = settings["summarize"]
    story.headline = _trim_words(
        humanize_headline(story.title, story.source_label), cfg["max_headline_words"]
    ).rstrip(" .,-:")
    story.teaser = make_teaser(story.headline, story.source_label)
    sentences = [
        x.strip() for x in re.split(r"(?<=[.!?])\s+", story.lead.summary or story.title)
        if x.strip()
    ]
    # Compact format: exactly one "what happened" sentence, regardless of
    # settings.max_bullets (that setting is for older/other callers).
    story.bullets = (
        [_clip(depersonalize(sentences[0], story.source_label), cfg["max_bullet_chars"])]
        if sentences else []
    )
    story.body = story.bullets[0] if story.bullets else ""
    story.script_line = f"{story.headline}. {story.body}"
    # No model available: name the concrete consequence we can defend from the
    # category alone, rather than inventing an impact claim.
    why = _fallback_why(story.category, index)
    story.why_it_matters = why
    story.why_bullets = [why]
    story.take = ""  # dropped from the compact format entirely


def _fallback(stories: list[Story], settings: dict, date: str) -> Edition:
    """Extractive copy for every given story, used when no API key is set."""
    for i, story in enumerate(stories):
        _fallback_one(story, settings, i)

    if len(stories) == 1:
        s = stories[0]
        intro_line = f"Today's signal: {s.headline}."
        caption = f"{s.headline}\n\n{s.body}\n\n@techtalesengineering"
        yt_title = f"{s.headline} - {date}"
    else:
        intro_line = "Today's signals: " + "; ".join(s.headline for s in stories) + "."
        caption = "\n\n".join(f"{s.headline}\n{s.body}" for s in stories) + \
            "\n\n@techtalesengineering"
        yt_title = f"{len(stories)} AI stories today - {date}"

    return Edition(
        date=date,
        stories=stories,
        intro="Today in AI",
        outro=stories[0].teaser or stories[0].headline,
        intro_line=intro_line,
        caption=caption,
        yt_title=yt_title,
        yt_description="\n".join(f"{s.headline}: {s.link}" for s in stories),
    )


def summarize(stories: list[Story], settings: dict, date: str | None = None) -> Edition:
    """Write up every story the editorial gate chose (1-3 of them).

    All stories were already independently selected by aidaily.editorial -
    this writes each one up in the compact format (headline + one "what
    happened" sentence + one "why it matters" sentence, no ranking or
    dropping here) and builds the edition-level caption/YouTube fields to
    cover all of them.
    """
    date = date or datetime.now().strftime("%Y-%m-%d")
    cfg = settings["summarize"]

    if not stories:
        raise ValueError("summarize() called with no stories")

    api_key = env("ANTHROPIC_API_KEY")
    if not api_key:
        log.warning("ANTHROPIC_API_KEY not set - using extractive fallback copy")
        return _fallback(stories, settings, date)

    import anthropic

    # SEG_WORDS is a total budget across every story's script_line, not per
    # story - see the SPOKEN SCRIPT LINE rule in SYSTEM.
    seg_words = max(12 * len(stories), cfg["script_target_words"])
    system = (
        SYSTEM.replace("HEADLINE_WORDS", str(cfg["max_headline_words"]))
        .replace("MAX_BULLET_CHARS", str(cfg["max_bullet_chars"]))
        .replace("SEG_WORDS", str(seg_words))
    )
    user = "\n".join(_story_block(i, s) for i, s in enumerate(stories))

    client = anthropic.Anthropic(api_key=api_key)
    # Real headroom, not the tightest budget that happens to fit an easy
    # story: a truncated response fails to parse as JSON and silently falls
    # back to the extractive writer even though the model itself was fine.
    # Scales with story count since the response now covers all of them.
    max_tokens = 2048 * len(stories) + 1024
    resp = client.messages.create(
        model=cfg["model"], max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": user}],
    )
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", resp.content[0].text.strip())

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        if resp.stop_reason == "max_tokens":
            log.error(
                "model response was truncated at max_tokens=%d before it "
                "finished valid JSON - falling back to extractive copy. If "
                "this recurs, raise max_tokens further.", max_tokens,
            )
        else:
            log.error(
                "model returned non-JSON (stop_reason=%s), falling back to "
                "extractive copy", resp.stop_reason,
            )
        return _fallback(stories, settings, date)

    story_data = data.get("stories") or []
    if len(story_data) != len(stories):
        log.error(
            "model returned copy for %d stories but %d were requested - "
            "falling back to extractive copy rather than mismatching them",
            len(story_data), len(stories),
        )
        return _fallback(stories, settings, date)

    for story, sd in zip(stories, story_data):
        story.headline = _trim_words(
            sd.get("headline") or humanize_headline(story.title, story.source_label),
            cfg["max_headline_words"],
        ).rstrip(" .,-:")
        story.teaser = make_teaser(story.headline, story.source_label).rstrip(" .,-:")

        what = (sd.get("what_happened") or "").strip()
        story.bullets = [_clip(what, cfg["max_bullet_chars"])] if what else []
        story.body = story.bullets[0] if story.bullets else ""

        why = (sd.get("why_it_matters") or "").strip()
        story.why_bullets = [_clip(why, cfg["max_bullet_chars"])] if why else []
        # Legacy single-line field, kept for anything (e.g. make_edition.py)
        # that still reads it.
        story.why_it_matters = _clip(
            story.why_bullets[0] if story.why_bullets else _fallback_why(story.category, 0), 95
        )

        story.take = ""  # dropped from the compact format entirely
        story.script_line = sd.get("script_line") or f"{story.headline}. {story.body}"

    desc = data.get("yt_description", "")
    for story in stories:
        if story.link and story.link not in desc:
            desc += f"\n{story.headline}: {story.link}"

    default_yt_title = (
        f"{stories[0].headline} - {date}" if len(stories) == 1
        else f"{len(stories)} AI stories today - {date}"
    )
    default_intro_line = (
        f"Today's signal: {stories[0].headline}." if len(stories) == 1
        else "Today's signals: " + "; ".join(s.headline for s in stories) + "."
    )

    return Edition(
        date=date,
        stories=stories,
        intro="Today in AI",
        outro=stories[0].teaser or stories[0].headline,
        intro_line=default_intro_line,
        caption=data.get("caption", ""),
        yt_title=data.get("yt_title") or default_yt_title,
        yt_description=desc,
    )
