import json
from pathlib import Path

import pytest

from jina_clone.briefing.config import SectionDef
from jina_clone.briefing.generator import (
    GeneratorFailure,
    _briefs_system_prompt,
    _front_matter_system_prompt,
    _panel_system_prompt,
    _slack_digest_system_prompt,
    generate_briefs,
    generate_front_matter,
    generate_panel,
    generate_slack_digest,
)
from jina_clone.briefing.schema import (
    Brief, DataPoint, FrontMatter, LeadStory, OnThisDay, Panel, SlackDigest,
)


FIXTURE = Path("jina_clone/briefing/fixtures/sample_briefing.json")
GOOD_BRIEFING = json.loads(FIXTURE.read_text())


WEATHER = {
    "temp_high": 70, "temp_low": 50, "conditions": "x",
    "sunrise": "6:00", "sunset": "8:00", "daylight": "14h 00m",
}


def _front_matter_payload(lead_source_url: str = "https://a") -> str:
    return json.dumps({
        "lead": GOOD_BRIEFING["lead"],
        "lead_source_url": lead_source_url,
        "pull_quote": GOOD_BRIEFING["pull_quote"],
        "data_point": GOOD_BRIEFING["data_point"],
        "on_this_day": GOOD_BRIEFING["on_this_day"],
    })


def _panel_payload(section: str = "National") -> str:
    panel = next(p for p in GOOD_BRIEFING["panels"] if p["section"] == section)
    return json.dumps(panel)


def _briefs_payload() -> str:
    return json.dumps({"briefs": GOOD_BRIEFING["briefs"]})


def _articles():
    return [
        {"title": "t1", "link": "https://a", "source": "S1",
         "content": "body1", "category": "us_national_news"},
        {"title": "t2", "link": "https://b", "source": "S2",
         "content": "body2", "category": "us_local_news"},
    ]


# ------------- front matter -------------

async def test_front_matter_happy_path():
    async def fake(client, prompt: str) -> str:
        return _front_matter_payload("https://a")

    fm = await generate_front_matter(
        articles=_articles(), weather=WEATHER,
        today="Sat", volume="Vol", title="The Morning Fox",
        call_llm=fake, client=None,
    )
    assert isinstance(fm, FrontMatter)
    assert fm.lead_source_url == "https://a"


async def test_front_matter_retries_once_on_bad_json():
    attempts = [json.dumps({"lead": "x"}), _front_matter_payload("https://a")]
    async def fake(client, prompt: str) -> str:
        return attempts.pop(0)

    fm = await generate_front_matter(
        articles=_articles(), weather=WEATHER,
        today="Sat", volume="Vol", title="The Morning Fox",
        call_llm=fake, client=None,
    )
    assert isinstance(fm, FrontMatter)


async def test_front_matter_retries_on_first_call_failure():
    # A transient call failure (e.g. `claude -p exited 1`) on the FIRST
    # attempt must be retried, not propagated. Reproduces the 2026-05-29
    # morning emergency-edition incident: a concurrent claude -p call exited 1
    # and _call_with_retry let it through because the first call_llm sat
    # outside the try block.
    calls = {"n": 0}

    async def fake(client, prompt: str) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise GeneratorFailure("claude -p exited 1: ")
        return _front_matter_payload("https://a")

    fm = await generate_front_matter(
        articles=_articles(), weather=WEATHER,
        today="Sat", volume="Vol", title="The Morning Fox",
        call_llm=fake, client=None,
    )
    assert isinstance(fm, FrontMatter)
    assert calls["n"] == 2


async def test_front_matter_double_call_failure_raises():
    # Both attempts failing at the call layer must still surface a failure
    # (and not loop forever).
    calls = {"n": 0}

    async def fake(client, prompt: str) -> str:
        calls["n"] += 1
        raise GeneratorFailure("claude -p exited 1: ")

    with pytest.raises(GeneratorFailure):
        await generate_front_matter(
            articles=_articles(), weather=WEATHER,
            today="Sat", volume="Vol", title="The Morning Fox",
            call_llm=fake, client=None,
        )
    assert calls["n"] == 2


async def test_front_matter_rejects_unknown_lead_url():
    # lead_source_url must match one of the input article links
    async def fake(client, prompt: str) -> str:
        return _front_matter_payload("https://not-in-input")

    with pytest.raises(GeneratorFailure):
        await generate_front_matter(
            articles=_articles(), weather=WEATHER,
            today="Sat", volume="Vol", title="The Morning Fox",
            call_llm=fake, client=None,
        )


async def test_front_matter_double_failure_raises():
    async def fake(client, prompt: str) -> str:
        return json.dumps({"bad": True})

    with pytest.raises(GeneratorFailure):
        await generate_front_matter(
            articles=_articles(), weather=WEATHER,
            today="Sat", volume="Vol", title="The Morning Fox",
            call_llm=fake, client=None,
        )


async def test_front_matter_resolves_lead_source():
    async def fake(client, prompt: str) -> str:
        return _front_matter_payload("https://a")

    fm = await generate_front_matter(
        articles=_articles(), weather=WEATHER,
        today="Sat", volume="Vol", title="The Morning Fox",
        call_llm=fake, client=None,
    )
    assert len(fm.lead.sources) == 1
    assert fm.lead.sources[0].url == "https://a"
    assert fm.lead.sources[0].source == "S1"


# ------------- panel -------------

NATIONAL_SECTION = SectionDef(
    key="national", title="National",
    categories=("us_national_news", "us_local_news", "policy"),
    limit=40,
)


async def test_generate_panel_happy_path():
    async def fake(client, prompt: str) -> str:
        return _panel_payload("National")

    panel = await generate_panel(
        section=NATIONAL_SECTION, articles=_articles(),
        exclude_urls=set(), title="The Morning Fox",
        call_llm=fake, client=None,
    )
    assert isinstance(panel, Panel)
    assert panel.section == "National"


async def test_generate_panel_filters_exclude_urls():
    """Articles whose `link` is in exclude_urls must not appear in the prompt."""
    seen_prompts: list[str] = []
    async def fake(client, prompt: str) -> str:
        seen_prompts.append(prompt)
        return _panel_payload("National")

    await generate_panel(
        section=NATIONAL_SECTION, articles=_articles(),
        exclude_urls={"https://a"}, title="The Morning Fox",
        call_llm=fake, client=None,
    )
    assert "https://a" not in seen_prompts[0]
    assert "https://b" in seen_prompts[0]


async def test_generate_panel_double_failure_raises():
    async def fake(client, prompt: str) -> str:
        return json.dumps({"bad": True})

    with pytest.raises(GeneratorFailure):
        await generate_panel(
            section=NATIONAL_SECTION, articles=_articles(),
            exclude_urls=set(), title="The Morning Fox",
            call_llm=fake, client=None,
        )


# ------------- briefs -------------

async def test_generate_briefs_happy_path():
    async def fake(client, prompt: str) -> str:
        return _briefs_payload()

    briefs = await generate_briefs(
        articles=_articles(), exclude_urls=set(), title="The Morning Fox",
        call_llm=fake, client=None,
    )
    assert isinstance(briefs, list)
    assert len(briefs) >= 5
    assert all(isinstance(b, Brief) for b in briefs)


async def test_generate_briefs_double_failure_raises():
    async def fake(client, prompt: str) -> str:
        return json.dumps({"bad": True})

    with pytest.raises(GeneratorFailure):
        await generate_briefs(
            articles=_articles(), exclude_urls=set(), title="The Morning Fox",
            call_llm=fake, client=None,
        )


# ------------- prompt builders carry title -------------

def test_front_matter_prompt_builder_carries_title():
    morning = _front_matter_system_prompt("The Morning Fox")
    evening = _front_matter_system_prompt("The Evening Fox")
    assert "The Morning Fox" in morning
    assert "The Evening Fox" in evening
    assert "The Morning Fox" not in evening


def test_panel_prompt_builder_carries_title():
    morning = _panel_system_prompt(NATIONAL_SECTION, "The Morning Fox")
    evening = _panel_system_prompt(NATIONAL_SECTION, "The Evening Fox")
    assert "The Morning Fox" in morning
    assert "The Evening Fox" in evening
    assert "The Morning Fox" not in evening


def test_briefs_prompt_builder_carries_title():
    morning = _briefs_system_prompt("The Morning Fox")
    evening = _briefs_system_prompt("The Evening Fox")
    assert "The Morning Fox" in morning
    assert "The Evening Fox" in evening
    assert "The Morning Fox" not in evening


def test_front_matter_prompt_contains_length_rule():
    prompt = _front_matter_system_prompt("The Morning Fox")
    assert "LENGTH RULE" in prompt
    assert "HARD LIMIT" in prompt
    assert prompt.index("CONSEQUENCE RULE") < prompt.index("LENGTH RULE") < prompt.index("STRUCTURE")


def test_panel_prompt_contains_length_rule():
    prompt = _panel_system_prompt(NATIONAL_SECTION, "The Morning Fox")
    assert "LENGTH RULE" in prompt
    assert "HARD LIMIT" in prompt
    assert prompt.index("CONSEQUENCE RULE") < prompt.index("LENGTH RULE") < prompt.index("STRUCTURE")


def test_briefs_prompt_contains_length_rule():
    prompt = _briefs_system_prompt("The Morning Fox")
    assert "LENGTH RULE" in prompt
    assert "HARD LIMIT" in prompt
    assert prompt.index("CONSEQUENCE RULE") < prompt.index("LENGTH RULE") < prompt.index("STRUCTURE")


# ------------- slack digest -------------

def _digest_payload(urls=("https://a", "https://b"), category="news") -> str:
    return json.dumps({
        "lead": "Two stories matter today.",
        "items": [
            {"url": u, "title": f"Title {i}", "blurb": "One line.",
             "category": category}
            for i, u in enumerate(urls)
        ],
    })


async def test_slack_digest_happy_path():
    async def fake(client, prompt: str) -> str:
        return _digest_payload()

    digest = await generate_slack_digest(
        articles=_articles(), edition_label="Morning",
        call_llm=fake, client=None,
    )
    assert isinstance(digest, SlackDigest)
    assert [i.url for i in digest.items] == ["https://a", "https://b"]
    assert [i.category for i in digest.items] == ["news", "news"]
    # Source is derived from the input article by url, not LLM output.
    assert [i.source for i in digest.items] == ["S1", "S2"]


async def test_slack_digest_rejects_missing_category():
    async def fake(client, prompt: str) -> str:
        payload = json.loads(_digest_payload())
        for item in payload["items"]:
            del item["category"]
        return json.dumps(payload)

    with pytest.raises(GeneratorFailure):
        await generate_slack_digest(
            articles=_articles(), edition_label="Morning",
            call_llm=fake, client=None,
        )


async def test_slack_digest_rejects_unknown_category():
    async def fake(client, prompt: str) -> str:
        return _digest_payload(category="gossip")

    with pytest.raises(GeneratorFailure):
        await generate_slack_digest(
            articles=_articles(), edition_label="Morning",
            call_llm=fake, client=None,
        )


async def test_slack_digest_overrides_llm_source():
    async def fake(client, prompt: str) -> str:
        payload = json.loads(_digest_payload())
        for item in payload["items"]:
            item["source"] = "Hallucinated Times"
        return json.dumps(payload)

    digest = await generate_slack_digest(
        articles=_articles(), edition_label="Morning",
        call_llm=fake, client=None,
    )
    assert [i.source for i in digest.items] == ["S1", "S2"]


async def test_slack_digest_retries_once_on_bad_json():
    attempts = [json.dumps({"lead": "no items"}), _digest_payload()]

    async def fake(client, prompt: str) -> str:
        return attempts.pop(0)

    digest = await generate_slack_digest(
        articles=_articles(), edition_label="Morning",
        call_llm=fake, client=None,
    )
    assert isinstance(digest, SlackDigest)


async def test_slack_digest_rejects_hallucinated_url():
    async def fake(client, prompt: str) -> str:
        return _digest_payload(urls=("https://a", "https://hallucinated"))

    with pytest.raises(GeneratorFailure):
        await generate_slack_digest(
            articles=_articles(), edition_label="Morning",
            call_llm=fake, client=None,
        )


async def test_slack_digest_rejects_duplicate_urls():
    async def fake(client, prompt: str) -> str:
        return _digest_payload(urls=("https://a", "https://a"))

    with pytest.raises(GeneratorFailure):
        await generate_slack_digest(
            articles=_articles(), edition_label="Morning",
            call_llm=fake, client=None,
        )


def test_slack_digest_prompt_carries_edition():
    morning = _slack_digest_system_prompt("Morning")
    afternoon = _slack_digest_system_prompt("Afternoon")
    assert "Morning" in morning
    assert "Afternoon" in afternoon
    assert "Morning" not in afternoon
    assert "VOICE RULES" in morning


async def test_slack_digest_enforces_item_count_floor():
    # Floor is min(6, len(articles)). With 2 articles a 2-item payload
    # passes (covered by the happy path), but fewer items than articles
    # must be rejected: 1 item against 2 articles fails.
    async def fake(client, prompt: str) -> str:
        return _digest_payload(urls=("https://a",))

    with pytest.raises(GeneratorFailure):
        await generate_slack_digest(
            articles=_articles(), edition_label="Morning",
            call_llm=fake, client=None,
        )
