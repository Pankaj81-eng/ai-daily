"""Stage 2b - the editorial gate.

TechTales is not an AI news channel. It is an AI Engineering Signal Channel:
a filter, not a content mill. Passing verify.py's credibility checks makes a
story publishable, not worth publishing - this module decides whether ANY of
today's verified candidates actually clears that much higher bar, and if
none do, says so and stops. Publishing nothing is a correct, expected, and
frequent outcome, not a failure.

This is deliberately a judgment call an LLM makes, not a hand-written
heuristic - "would this channel's actual audience stop scrolling for this"
is not something keyword matching can answer. The one rule that IS enforced
in plain code, not a prompt, is the research/preprint hard filter in
verify.py: that one is a fact (independent corroboration exists or it
doesn't), not a judgment, so it does not depend on a model call to hold.

Scope is deliberately broader than US big-tech product launches - major AI
news from Chinese and European labs, company deals (acquisitions, funding,
investment), and country/government AI policy all count, evaluated on the
same bar as everything else, not as a lesser category.
"""

from __future__ import annotations

import json
import logging
import re

from .config import env
from .enrich import enrich_thin_candidates
from .models import Story

log = logging.getLogger(__name__)

# Lowered from 8.0 to 7.5 in mid-Aug 2026 after the genuinely-best story of
# the day repeatedly landing at 7.2-7.8 and getting rejected. Lowered again,
# 7.5 -> 7.0, on 22 Aug 2026 morning, after Mistral's Agentic Search launch -
# a major EU lab, called "genuinely useful... genuinely significant" by the
# model's own reasoning - still landed at 7.4 and got rejected even with
# enrich.py's real article text.
#
# Lowered again same day, 7.0 -> 6.0, at Pankaj's explicit request, WITHOUT
# new evidence of a 6-7 range near-miss - unlike every move above, this one
# is not backed by an observed pattern, just a preference for a higher
# publish frequency. Flagged at the time: the 5-7 range that day was mostly
# single-vendor AWS how-to posts and minor features the model itself called
# "one of many AWS blog posts" / "too incremental" - this move risks letting
# that tier through. If posts start feeling thin/promotional rather than
# signal, this is the first place to look; raising it back is a one-line
# change, not a rebuild.
SCORE_THRESHOLD = 6.0

# The threshold used to be hardcoded as literal "7.5" text in two places
# below (the SCORING and final-decision paragraphs), which meant a
# threshold change here silently stopped matching what the model was
# actually told the bar was - caught 22 Aug 2026 when SCORE_THRESHOLD moved
# to 7.0 but the prompt still said 7.5 twice. Fixed by writing a
# __SCORE_THRESHOLD__ sentinel below and substituting it after the string
# literal (see the str.replace() right after this string) rather than an
# f-string/.format(), since the JSON schema block further down has literal
# {braces} that would need escaping for either of those.
SYSTEM = """You are the Editor-in-Chief of TechTales.

TechTales is NOT an AI news channel. TechTales is an AI Engineering Signal
Channel.

TechTales is a growing, early-stage channel. Our audience is a real mix, not
a narrow engineering-only trade publication - AI/software engineers, QA
engineers, development and engineering managers, senior managers, technical
architects, tech founders, serious AI learners, and a general-public segment
who follow for the broader story rather than the technical detail.

Our reputation depends on filtering information, not producing content.
Publishing nothing is better than publishing noise.

MISSION: select the AI stories from today that are genuinely worth this
audience's time - zero, one, two, or three of them, never more. This is not
"pick the best N to fill a newsletter" - a story only makes the list if it
independently clears the bar on its own. A quiet day with zero qualifying
stories is a correct, expected outcome, not a failure. Do not treat "we
were given candidates" as a reason any of them must be published.

STORY SELECTION RULES

Reject stories involving:
- Minor research papers, academic papers without practical impact
- Benchmark improvements, incremental updates
- Small startup announcements, experimental models with no adoption
- Press releases with little significance
- Research with no near-term relevance to our audience's work or industry

Prioritize stories involving:
- OpenAI, Anthropic, Google, Microsoft, Meta, AWS, NVIDIA, GitHub, Cursor,
  Windsurf, and other major AI labs/platforms
- Chinese AI labs and companies - DeepSeek, Alibaba/Qwen, Zhipu/GLM,
  Moonshot/Kimi, and peers - held to exactly the same bar as US labs, not a
  lesser or "foreign" category
- European AI labs and companies, same standard
- Company deals of genuine significance - acquisitions, funding rounds,
  investments - regardless of company size, if the deal itself is a big
  enough story to matter to this audience
- Important open-source releases
- AI regulation and government/country-level AI policy action, from any
  country, not only the US or EU
- Enterprise AI adoption, developer tools

SOURCE QUALITY: prefer official company announcements, company blogs,
product release notes, and major technology publications. Never confuse a
source name with the actual news story - "arXiv" is a source, never a
headline; the headline is what the paper or story is actually about.

RELEVANCE TEST: would a meaningful slice of our actual audience - not just
the most senior engineer in the room - stop scrolling and spend 30 seconds
on this? A major acquisition, a significant funding round, or a
country-level AI policy shift can pass this test on its own market or
career significance, even without a narrow technical angle - it does not
need to be "actionable" in code to matter to a QA engineer, an engineering
manager, or someone just following the industry. If no one in that mix
would care, reject.

SCORING: score every candidate 1-10 on each of:
- engineering_impact
- business_impact
- adoption_potential
- practical_usefulness
- long_term_importance
average = the mean of those five. A story is only eligible for publication
if average >= __SCORE_THRESHOLD__. Every story that clears __SCORE_THRESHOLD__ AND passes every test below
is eligible - publish every eligible story, ranked highest-scoring first,
capped at 3. If more than 3 clear the bar, publish only the top 3. This is
not "always publish 3" - most days will have 0 or 1 eligible stories; 3 in
one day should be rare, only when the day genuinely produced that much
signal.

"WHY SHOULD I CARE" TEST: every eligible story must be completable as
"Our audience should care because ...". The completion can be a technical
reason (a new capability, a tool, an architecture shift) or a market/career
reason (what this deal or policy move means for where the industry, their
employer, or their role is headed) - either is valid, as long as it is
clear and specific. A vague "this is important" does not pass; a specific
consequence does. If you cannot complete that sentence clearly and
specifically for a story, it is not eligible, regardless of its score.

QUALITY CHECK before finalizing: would you personally share this with your
network, technical or not? Would it still matter in 30 days? Does a reader
walk away knowing something real, whether or not there is a concrete action
to take? Is it more signal than noise? If any answer is no for your top
candidate, publish nothing instead.

ALREADY COVERED: you will be shown what TechTales actually published over
the last two weeks (headline, date, company). A candidate does not need an
identical URL to count as already covered - a different article about the
same underlying feature, product, or event (a follow-up post, a "part 2",
the same launch covered by a second outlet) is still the same story to a
reader who already saw it. If a candidate is substantively a rehash or
minor extension of something already published, reject it regardless of
its score, and say so in that candidate's reasoning.

Score every candidate you are given, in the order given, even the ones you
will reject - explain briefly why each one does or does not clear the bar.
Then decide: every candidate scoring >= __SCORE_THRESHOLD__ average AND passing every test
above is eligible. Publish every eligible story, most important first,
capped at 3 - if none are eligible, publish nothing; that is a normal
outcome, not a failure to avoid.

Return ONLY valid JSON, no markdown fence, in exactly this shape:
{
  "scores": [
    {"index": 0,
     "engineering_impact": 1-10, "business_impact": 1-10,
     "adoption_potential": 1-10, "practical_usefulness": 1-10,
     "long_term_importance": 1-10,
     "average": <mean of the five, one decimal place>,
     "audience_should_care_because": "one sentence completing that test, or empty string if it cannot be completed",
     "reasoning": "one short sentence on why this does or does not clear the bar"}
  ],
  "publish_indices": [<indices of the stories to publish, most important first, 0-3 entries, empty list if none clear the bar>],
  "decision_reason": "one sentence explaining the final call - why these (or none), and why not more/fewer"
}
The "scores" array must have exactly one entry per candidate given, in the
same order, indices starting at 0."""

SYSTEM = SYSTEM.replace("__SCORE_THRESHOLD__", str(SCORE_THRESHOLD))


def _candidate_block(idx: int, story: Story, enriched_text: str | None = None) -> str:
    if enriched_text:
        source_text = enriched_text
        source_note = " (fetched from the article - the RSS summary was too thin to score)"
    else:
        source_text = story.lead.summary or "(none provided by feed)"
        source_note = ""
    return (
        f"--- CANDIDATE {idx} ---\n"
        f"Category: {story.category}\n"
        f"Primary source: {story.lead.source_name} (tier {story.best_tier})\n"
        f"All sources: {', '.join(story.sources)}\n"
        f"Independent sources corroborating it: {story.corroboration}\n"
        f"URL: {story.link}\n"
        f"Headline as published: {story.title}\n"
        f"Source text{source_note}: {source_text}\n"
    )


def _recent_block(recent_published: list[dict]) -> str:
    if not recent_published:
        return "ALREADY COVERED (last 14 days): nothing - this is a fresh start.\n"
    lines = [f"ALREADY COVERED (last 14 days, oldest first, {len(recent_published)} stories):"]
    for e in recent_published:
        company = f" [{e['company']}]" if e.get("company") else ""
        lines.append(f"  {e['date']}: {e['headline']}{company}")
    return "\n".join(lines) + "\n"


# Never more than this many stories in one edition, even on a genuinely
# strong day - see MISSION and the SCORING rule above. Most days should
# return 0 or 1, not the cap.
MAX_STORIES = 3


def select_stories(
    candidates: list[Story], settings: dict, recent_published: list[dict] | None = None,
) -> list[Story]:
    """The stories worth publishing today, ranked most important first.

    An empty list is a normal, frequent, correct result - it means "no
    newsletter today", not that anything went wrong. Capped at MAX_STORIES;
    each returned story independently cleared SCORE_THRESHOLD on its own -
    this is "publish everything that earned it, capped at 3", never "always
    fill 3 slots". `recent_published` (from aidaily.state.PublishedLog) lets
    the model recognise a same-theme rehash even when the specific
    article/URL is new - see the ALREADY COVERED rule in SYSTEM.
    """
    if not candidates:
        return []

    api_key = env("ANTHROPIC_API_KEY")
    if not api_key:
        # Degraded mode: we cannot apply the real editorial rubric without a
        # model, so fall back to a deliberately conservative proxy - only the
        # single top-ranked candidate, and only if it clears a floor that
        # roughly matches "not obviously noise" (a primary source, or real
        # independent corroboration). This exists so --dry-run and local
        # testing still work offline; it is NOT a substitute for the real
        # gate and should never run against real publishing.
        log.warning(
            "ANTHROPIC_API_KEY not set - using a conservative fallback "
            "instead of the real editorial gate (best_tier==1 or "
            "corroboration>=2 required)"
        )
        top = candidates[0]
        if top.best_tier == 1 or top.corroboration >= 2:
            return [top]
        return []

    import anthropic

    # Thin RSS summaries (a tagline, no facts) can make a genuinely
    # significant story unscoreable - see enrich.py's module docstring for
    # the real case (Mistral, 22 Aug 2026) that motivated this. Only the
    # candidates that actually need it get a live fetch; everyone else is
    # scored on their original summary exactly as before.
    enriched = enrich_thin_candidates(candidates, settings)

    user = (
        _recent_block(recent_published or [])
        + "\n"
        + "\n".join(
            _candidate_block(i, s, enriched.get(i)) for i, s in enumerate(candidates)
        )
    )
    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=settings["summarize"]["model"], max_tokens=4096, system=SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", resp.content[0].text.strip())

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.error(
            "editorial gate returned non-JSON (stop_reason=%s) - publishing "
            "nothing rather than guessing", resp.stop_reason,
        )
        return []

    scores_by_index: dict[int, dict] = {}
    for s in data.get("scores", []):
        log.info(
            "candidate %s: avg=%s  %s",
            s.get("index"), s.get("average"), s.get("reasoning", ""),
        )
        scores_by_index[s.get("index")] = s

    indices = data.get("publish_indices") or []
    reason = data.get("decision_reason", "")
    if not indices:
        log.info("editorial gate: NO NEWSLETTER TODAY - %s", reason)
        return []

    chosen: list[Story] = []
    for idx in indices[:MAX_STORIES]:
        if not (isinstance(idx, int) and 0 <= idx < len(candidates)):
            log.error("editorial gate returned out-of-range index %r - skipping it", idx)
            continue
        average = scores_by_index.get(idx, {}).get("average", 0)
        if average < SCORE_THRESHOLD:
            log.warning(
                "editorial gate picked index %s at average %.1f, below the "
                "%.1f threshold - skipping it rather than trusting a score "
                "under the bar", idx, average, SCORE_THRESHOLD,
            )
            continue
        chosen.append(candidates[idx])
        log.info("editorial gate: publishing candidate %d (avg %.1f)", idx, average)

    if not chosen:
        log.info(
            "editorial gate: NO NEWSLETTER TODAY - every picked index failed "
            "validation (out of range or below threshold)"
        )
    else:
        log.info(
            "editorial gate: publishing %d stor%s - %s",
            len(chosen), "y" if len(chosen) == 1 else "ies", reason,
        )
    return chosen
