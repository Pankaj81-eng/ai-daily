"""Tests for the credibility gate.

These are the tests that matter most: if verification regresses, the channel
starts publishing rumours under its own name.

    pip install pytest && python -m pytest tests/ -q
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aidaily import verify                     # noqa: E402
from aidaily.config import load_settings       # noqa: E402
from aidaily.models import Item                # noqa: E402
from tests.fixtures import items as fixture_items  # noqa: E402

SETTINGS = load_settings()


def _item(title, source, tier, link="https://example.com/x", outlinks=None, hours=3):
    return Item(
        title=title,
        link=link,
        summary="body text",
        published=datetime.now(timezone.utc) - timedelta(hours=hours),
        source_name=source,
        source_tier=tier,
        outlinks=outlinks or [],
    )


def _run(items):
    primaries = verify.primary_domains(items)
    stories = verify.cluster(items, SETTINGS["verify"]["cluster_similarity"])
    return verify.verify(stories, SETTINGS, primaries)


def _titles(stories):
    return {s.title for s in stories}


# --------------------------------------------------------------------------
# tier rules
# --------------------------------------------------------------------------

def test_tier1_publishes_alone():
    items = [_item("Lab ships a new model", "OpenAI Blog", 1,
                   "https://openai.com/blog/a")]
    assert len(_run(items)) == 1


def test_lone_tier2_rumour_is_rejected():
    items = [_item("Startup reportedly raising at a higher valuation",
                   "VentureBeat AI", 2, "https://venturebeat.com/a")]
    assert _run(items) == []


def test_two_independent_tier2_reports_pass():
    items = [
        _item("Regulator publishes compliance guidance for AI models",
              "TechCrunch AI", 2, "https://techcrunch.com/a"),
        _item("Compliance guidance for AI models published by regulator",
              "Ars Technica AI", 2, "https://arstechnica.com/b"),
    ]
    kept = _run(items)
    assert len(kept) == 1
    assert kept[0].corroboration == 2


def test_tier2_with_primary_outlink_passes_alone():
    items = [
        _item("Chipmaker details new accelerator", "The Verge AI", 2,
              "https://theverge.com/a",
              outlinks=["https://blogs.nvidia.com/blog/accel/"]),
        _item("Announcing our new accelerator", "NVIDIA Blog", 1,
              "https://blogs.nvidia.com/blog/accel/"),
    ]
    kept = _run(items)
    # They are one story (the press piece cites the primary), and it survives.
    assert len(kept) == 1
    assert kept[0].best_tier == 1


def test_aggregator_alone_is_always_rejected():
    items = [_item("Show HN: my AI side project", "Hacker News (AI front page)",
                   3, "https://news.ycombinator.com/item?id=1")]
    kept = _run(items)
    assert kept == []


def test_lone_arxiv_paper_is_hard_rejected():
    """A paper with no independent pickup has no evidence of real impact."""
    items = [_item("A new attention variant for long-context inference",
                   "arXiv cs.LG", 1, "https://arxiv.org/abs/2601.00001")]
    assert _run(items) == []


def test_arxiv_paper_with_independent_pickup_is_judged_normally():
    """A paper a real outlet also covered gets real corroboration credit."""
    items = [
        _item("A new attention variant for long-context inference",
              "arXiv cs.LG", 1, "https://arxiv.org/abs/2601.00001"),
        _item("Researchers unveil a faster attention mechanism",
              "TechCrunch AI", 2, "https://techcrunch.com/attention-variant",
              outlinks=["https://arxiv.org/abs/2601.00001"]),
    ]
    assert len(_run(items)) == 1


# --------------------------------------------------------------------------
# clustering
# --------------------------------------------------------------------------

def test_citation_link_merges_stories():
    """A press story citing a primary must not occupy a second slide."""
    a = _item("Chipmaker details next-generation inference accelerator",
              "The Verge AI", 2, "https://theverge.com/nv",
              outlinks=["https://blogs.nvidia.com/blog/accel/"])
    b = _item("Announcing our next-generation inference platform",
              "NVIDIA Blog", 1, "https://blogs.nvidia.com/blog/accel/")
    stories = verify.cluster([a, b], SETTINGS["verify"]["cluster_similarity"])
    assert len(stories) == 1


def test_rewritten_headlines_merge():
    a = _item("EU AI Act enforcement body publishes first compliance guidance",
              "TechCrunch AI", 2, "https://techcrunch.com/a")
    b = _item("Europe issues first compliance guidance under the AI Act",
              "Ars Technica AI", 2, "https://arstechnica.com/b")
    stories = verify.cluster([a, b], SETTINGS["verify"]["cluster_similarity"])
    assert len(stories) == 1


def test_unrelated_stories_do_not_merge():
    a = _item("New embedding model released for retrieval", "OpenAI Blog", 1,
              "https://openai.com/a")
    b = _item("Chip export controls tightened by regulators", "Reuters Technology",
              2, "https://reuters.com/b")
    stories = verify.cluster([a, b], SETTINGS["verify"]["cluster_similarity"])
    assert len(stories) == 2


def test_canonicalisation_ignores_tracking_params():
    a = _item("Same story", "TechCrunch AI", 2,
              "https://techcrunch.com/post/?utm_source=rss")
    b = _item("Totally different words here entirely", "Ars Technica AI", 2,
              "https://www.techcrunch.com/post")
    stories = verify.cluster([a, b], SETTINGS["verify"]["cluster_similarity"])
    assert len(stories) == 1


# --------------------------------------------------------------------------
# ranking
# --------------------------------------------------------------------------

def test_hedged_story_ranks_below_primary():
    items = [
        _item("Company might be considering a new model, sources say",
              "TechCrunch AI", 2, "https://techcrunch.com/a"),
        _item("Company might be considering a new model, reportedly",
              "Ars Technica AI", 2, "https://arstechnica.com/b"),
        _item("We are releasing a new model today", "OpenAI Blog", 1,
              "https://openai.com/c"),
    ]
    kept = sorted(_run(items), key=lambda s: s.score, reverse=True)
    assert kept[0].best_tier == 1, "a primary announcement must outrank a rumour"


def test_full_fixture_set_rejects_the_right_stories():
    kept = _run(fixture_items())
    titles = " ".join(_titles(kept)).lower()
    assert "reportedly in talks" not in titles, "lone rumour leaked through"
    assert "show hn" not in titles, "aggregator item leaked through"
    assert "sparse attention" not in titles, (
        "lone arXiv item with no independent corroboration leaked through"
    )
    assert len(kept) == 4


def test_dedupe_respects_seen_store():
    class FakeSeen:
        def __init__(self, uids):
            self.uids = uids

        def has(self, uid):
            return uid in self.uids

    items = fixture_items()
    kept = _run(items)
    already = {i.uid for i in kept[0].items}
    remaining = verify.select(kept, SETTINGS, FakeSeen(already))
    assert kept[0].title not in _titles(remaining)


# --------------------------------------------------------------------------
# hard rejects and editorial categories (TechTales content rules)
# --------------------------------------------------------------------------

def test_rumour_language_hard_rejects_press_story():
    items = [
        _item("Company reportedly preparing a new chip", "TechCrunch AI", 2,
              "https://techcrunch.com/a"),
        _item("Chipmaker is said to be preparing new silicon", "The Verge AI", 2,
              "https://theverge.com/b"),
    ]
    # Two independent reports would normally pass; rumour language overrides.
    assert _run(items) == []


def test_rumour_words_do_not_suppress_a_primary_announcement():
    """A tier-1 source describing its own work must never be hard-rejected."""
    items = [_item("We are releasing a model that could change workflows",
                   "OpenAI Blog", 1, "https://openai.com/a")]
    assert len(_run(items)) == 1


def test_clickbait_is_rejected_at_every_tier():
    items = [_item("This changes everything for AI developers", "OpenAI Blog", 1,
                   "https://openai.com/a")]
    assert _run(items) == []


def test_leak_language_is_rejected():
    items = [
        _item("Leaked documents show upcoming model plans", "VentureBeat AI", 2,
              "https://venturebeat.com/a"),
        _item("Leak reveals upcoming model roadmap", "TechCrunch AI", 2,
              "https://techcrunch.com/b"),
    ]
    assert _run(items) == []


def test_category_classification():
    cfg = SETTINGS["verify"]

    def cat(title, summary=""):
        story = verify.Story(items=[_item(title, "OpenAI Blog", 1)])
        story.items[0].summary = summary
        return verify.classify(story, cfg)

    assert cat("OpenAI releases a new model family") == "model_release"
    assert cat("Google adds AI agents to Workspace") == "product_launch"
    assert cat("Europe publishes guidance under the AI Act") == "regulation"
    assert cat("Startup raises funding at a new valuation") == "business"


def test_whole_word_matching_avoids_false_positives():
    """'act' must match 'the AI Act' but never 'impact' or 'actually'."""
    cfg = SETTINGS["verify"]
    story = verify.Story(items=[
        _item("New model has real impact on developer productivity", "OpenAI Blog", 1)
    ])
    assert verify.classify(story, cfg) != "regulation"


def test_launches_outrank_funding_rounds():
    items = [
        _item("AI startup raises new funding round", "OpenAI Blog", 1,
              "https://openai.com/a"),
        _item("OpenAI releases a new reasoning model family", "Anthropic News", 1,
              "https://anthropic.com/b"),
    ]
    ranked = sorted(_run(items), key=lambda s: s.score, reverse=True)
    assert ranked[0].category == "model_release"


def test_selection_caps_one_story_per_source():
    class NoSeen:
        def has(self, uid):
            return False

    items = [
        _item("OpenAI releases model one", "OpenAI Blog", 1, "https://openai.com/1"),
        _item("OpenAI launches product two", "OpenAI Blog", 1, "https://openai.com/2"),
        _item("Google adds agents to Workspace", "Google DeepMind Blog", 1,
              "https://deepmind.google/3"),
        _item("Nvidia unveils new accelerator", "NVIDIA Blog", 1,
              "https://blogs.nvidia.com/4"),
    ]
    picked = verify.select(_run(items), SETTINGS, NoSeen())
    sources = [s.lead.source_name for s in picked]
    assert len(picked) == 3
    assert len(set(sources)) == 3, f"expected one per source, got {sources}"


# --------------------------------------------------------------------------
# copy rewriting (V1 refinements)
# --------------------------------------------------------------------------

from aidaily.summarize import (                      # noqa: E402
    depersonalize, humanize_headline, make_teaser,
)


def test_press_release_headlines_are_rewritten():
    """The exact pattern flagged in review must not survive.

    "next-generation" is also plained down to "new" - corporate vocabulary is
    stripped in the same pass as the first-person framing.
    """
    assert humanize_headline(
        "Announcing our next-generation inference platform", "NVIDIA"
    ) == "NVIDIA launches new inference platform"


def test_first_person_headlines_are_rewritten():
    out = humanize_headline("We are excited to announce our new agent framework",
                            "Google DeepMind")
    assert out.startswith("Google DeepMind launches")
    assert " we " not in f" {out.lower()} "


def test_headline_already_naming_company_keeps_its_structure():
    """No third-person rewrite needed, but jargon is still plained down."""
    out = humanize_headline(
        "Nvidia details next-generation inference accelerator", "Nvidia"
    )
    assert out.startswith("Nvidia details")
    assert "next-generation" not in out


def test_teaser_is_shorter_than_headline_and_keeps_proper_nouns():
    headline = humanize_headline("Meet the new Claude", "Anthropic")
    teaser = make_teaser(headline, "Anthropic")
    assert "Claude" in teaser, "proper nouns must not be lowercased"
    assert len(teaser.split()) <= len(headline.split())


def test_teaser_does_not_credit_a_publisher_as_the_subject():
    """A story about Europe reported by TechCrunch is not 'TechCrunch: ...'."""
    teaser = make_teaser(
        "Europe issues first compliance guidance under the AI Act", "TechCrunch"
    )
    assert not teaser.startswith("TechCrunch")


def test_teaser_never_ends_on_a_function_word():
    teaser = make_teaser(
        "Europe issues first compliance guidance under the AI Act", "TechCrunch"
    )
    assert teaser.split()[-1].lower() not in {"under", "the", "a", "in", "of", "with"}


def test_bullets_lose_first_person_voice():
    out = depersonalize("Architectural detail on our new inference accelerator.",
                        "NVIDIA")
    assert "our" not in out.lower()
    out2 = depersonalize("We are releasing a new model.", "OpenAI")
    assert out2.startswith("OpenAI is releasing")


# --------------------------------------------------------------------------
# news-style headlines and story-relevant imagery (final refinements)
# --------------------------------------------------------------------------

from aidaily.images import detect_company            # noqa: E402
from aidaily.models import Edition, Story             # noqa: E402
from aidaily.summarize import plainify               # noqa: E402


def test_headlines_hit_the_target_news_style():
    assert humanize_headline(
        "Announcing our next-generation inference platform", "NVIDIA"
    ) == "NVIDIA launches new inference platform"
    assert humanize_headline(
        "Open-weights model family released with permissive licence", "Hugging Face"
    ) == "Hugging Face open-sources model family"


def test_headlines_stay_within_news_length():
    long_title = ("Announcing our next-generation state-of-the-art inference "
                  "platform for enterprise customers worldwide today")
    out = humanize_headline(long_title, "NVIDIA", max_words=8)
    assert len(out.split()) <= 8


def test_headline_never_ends_on_a_dangling_preposition():
    out = humanize_headline(
        "Open-weights model family released with permissive licence", "Hugging Face"
    )
    assert out.split()[-1].lower() not in {"with", "for", "under", "using", "from"}


def test_corporate_vocabulary_is_plain_english():
    assert "next-generation" not in plainify("our next-generation platform").lower()
    assert "open-source" in plainify("open-weights model family").lower()


def test_imagery_follows_the_story_not_the_publisher():
    """A TechCrunch article about Nvidia must not show the TechCrunch logo."""
    story = Story(items=[_item(
        "Nvidia details new inference accelerator", "TechCrunch AI", 2,
        "https://techcrunch.com/nvidia")])
    detected = detect_company(story)
    assert detected is not None
    assert detected[1] == "nvidia.com"


def test_unknown_company_falls_back_gracefully():
    story = Story(items=[_item("Small startup launches a tool", "TechCrunch AI", 2)])
    assert detect_company(story) is None


def test_subject_never_falls_back_to_the_source_name():
    """The exact 'arXiv becomes the visual headline' bug: when no company can
    be identified, the generated panel and slide footers must show the
    editorial category, never the reporting outlet or research-repo feed
    name - the subject is what the story is ABOUT, not who is telling it."""
    from aidaily.render_carousel import _slide_specs

    story = Story(items=[_item(
        "A new attention variant for long-context inference",
        "arXiv cs.LG", 1, "https://arxiv.org/abs/2601.00002",
    )])
    story.headline = "New attention variant cuts inference cost"
    story.category = "research"
    edition = Edition(date="2026-08-14", stories=[story])

    spec = _slide_specs(edition, SETTINGS)[0]
    assert spec["subject"] != story.source_label
    assert spec["subject"] == "Research"
    # The source is still shown - just never as the subject.
    assert spec["source"] == "arXiv cs.LG"


# --------------------------------------------------------------------------
# why it matters + article imagery (V1 final)
# --------------------------------------------------------------------------

from aidaily.images import _srcset_largest          # noqa: E402
from aidaily.summarize import _fallback_why         # noqa: E402


def test_the_published_story_gets_a_why_it_matters_without_a_model():
    """summarize() writes up every story the editorial gate chose (1-3 of
    them) - confirm the fallback path fills why_it_matters for a single
    story when no API key is configured."""
    from aidaily.summarize import summarize
    stories = verify.select(_run(fixture_items()), SETTINGS,
                            type("S", (), {"has": lambda self, u: False})())[:1]
    edition = summarize(stories, SETTINGS, "2026-08-14")
    assert len(edition.stories) == 1
    assert edition.stories[0].why_it_matters


def test_summarize_writes_up_every_story_given():
    """Phase 2: summarize() now writes up every story the editorial gate
    selected (up to 3), not just the first - each gets its own headline,
    one "what happened" bullet, and one "why it matters" bullet."""
    from aidaily.summarize import summarize
    stories = verify.select(_run(fixture_items()), SETTINGS,
                            type("S", (), {"has": lambda self, u: False})())
    assert len(stories) > 1, "fixture needs 2+ passing stories for this test to mean anything"
    original_links = [s.link for s in stories]
    edition = summarize(stories, SETTINGS, "2026-08-14")
    assert len(edition.stories) == len(stories)
    for s in edition.stories:
        assert s.headline
        assert len(s.bullets) == 1, "compact format: exactly one what-happened bullet"
        assert len(s.why_bullets) == 1, "compact format: exactly one why-it-matters bullet"
        assert s.take == "", "TechTales Take is dropped entirely from the compact format"
    # summarize() must preserve input order - a caller zips stories/data by
    # position, so a silent reorder would mismatch copy onto the wrong story.
    assert [s.link for s in edition.stories] == original_links


def test_same_category_stories_get_different_takeaways():
    """Two model releases must not show an identical line on adjacent slides."""
    a = _fallback_why("model_release", 0)
    b = _fallback_why("model_release", 1)
    assert a != b


def test_unknown_category_still_returns_a_takeaway():
    assert _fallback_why("nonsense", 0)


def test_srcset_picks_the_largest_image():
    got = _srcset_largest("small.jpg 320w, medium.jpg 800w, large.jpg 1600w")
    assert got == "large.jpg"


def test_srcset_handles_entries_without_widths():
    assert _srcset_largest("only.jpg") == "only.jpg"


# --------------------------------------------------------------------------
# editorial pool visibility + "already covered" rehash detection
# --------------------------------------------------------------------------

def test_top_candidates_does_not_silently_cap_at_eight():
    """Regression: top_candidates() used to hard-cap at 8 by default,
    contradicting its own docstring ("does not cap... needs the real ranked
    pool"). A prolific source could fill every visible slot on the crude
    pre-LLM score below, hiding a bigger story from a quieter source past
    position 8. The editorial LLM gate must see everything verify.py passed,
    up to the generous settings.verify.editorial_pool_size ceiling."""
    class NoSeen:
        def has(self, uid):
            return False

    stories = []
    for i in range(15):
        s = Story(items=[_item(f"Story number {i}", "TechCrunch AI", 2,
                                link=f"https://example.com/{i}")])
        s.score = float(i)  # distinct, ascending
        stories.append(s)

    got = verify.top_candidates(stories, NoSeen())
    assert len(got) == 15, "default limit must not silently trim a normal-sized pool"
    # still genuinely ranked, highest score first
    assert got[0].score == 14.0


def test_published_log_roundtrip_and_recent_ordering():
    import tempfile
    from pathlib import Path as P
    from aidaily.state import PublishedLog

    with tempfile.TemporaryDirectory() as d:
        path = P(d) / "published_log.json"
        log1 = PublishedLog(path)
        log1.add("2026-08-19", "AWS lets AI agents make payments", "Amazon", "product_launch")
        log1.add("2026-08-20", "Gemini 3.7 Flash launches", "Google", "model_release")
        log1.save()

        log2 = PublishedLog(path)  # fresh instance, reloaded from disk
        recent = log2.recent()
        assert [e["headline"] for e in recent] == [
            "AWS lets AI agents make payments", "Gemini 3.7 Flash launches",
        ]
        assert recent[0]["company"] == "Amazon"


def test_editorial_recent_block_mentions_past_headlines():
    from aidaily.editorial import _recent_block

    entries = [{"date": "2026-08-19", "headline": "AWS lets AI agents make payments",
                "company": "Amazon", "category": "product_launch"}]
    block = _recent_block(entries)
    assert "AWS lets AI agents make payments" in block
    assert "2026-08-19" in block


def test_editorial_recent_block_empty_is_explicit_not_blank():
    from aidaily.editorial import _recent_block

    block = _recent_block([])
    assert "nothing" in block.lower()


# --------------------------------------------------------------------------
# Phase 2: multi-story (0-3) editorial selection + adaptive slide count
# --------------------------------------------------------------------------

def test_select_stories_offline_fallback_returns_a_list(monkeypatch):
    """No API key: the conservative offline fallback must return a list
    (possibly empty), never a bare Story or None - callers now always
    expect list-shaped output from select_stories(). Forces the no-key path
    via monkeypatch rather than assuming the ambient environment has none -
    a real ANTHROPIC_API_KEY is routinely exported in dev shells here."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from aidaily.editorial import select_stories

    strong = Story(items=[_item("Tier-1 launch", "OpenAI Blog", 1)])
    strong.best_tier = 1
    weak = Story(items=[_item("Unverified blip", "Random Blog", 3)])
    weak.best_tier = 3
    weak.corroboration = 1

    assert select_stories([strong], SETTINGS) == [strong]
    assert select_stories([weak], SETTINGS) == []
    assert select_stories([], SETTINGS) == []


def test_slide_count_scales_with_story_count():
    """1 cover/headline + 1 per story + 1 follow = N+2, for N in 1..3 -
    the exact formula agreed for the compact multi-story layout."""
    from aidaily.render_carousel import _slide_specs

    def _story(headline, category="product_launch"):
        s = Story(items=[_item(headline, "TechCrunch AI", 2)])
        s.headline, s.teaser, s.category = headline, headline[:20], category
        s.bullets, s.why_bullets = ["What happened."], ["Why it matters."]
        return s

    for n in (1, 2, 3):
        stories = [_story(f"Story {i}") for i in range(n)]
        edition = Edition(date="2026-08-21", stories=stories)
        specs = _slide_specs(edition, SETTINGS)
        assert len(specs) == n + 2, f"expected {n + 2} slides for {n} stories, got {len(specs)}"
        assert specs[-1]["kind"] == "follow"
        assert [s["kind"] for s in specs].count("story") == n
        if n == 1:
            assert specs[0]["kind"] == "headline"
        else:
            assert specs[0]["kind"] == "cover"
            assert len(specs[0]["teasers"]) == n
