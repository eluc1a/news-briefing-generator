import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from jina_clone.briefing.generator import (
    GeneratorFailure,
    build_user_message,
    generate,
)
from jina_clone.briefing.schema import Briefing


FIXTURE = Path("jina_clone/briefing/fixtures/sample_briefing.json")
GOOD_JSON = FIXTURE.read_text()


def _articles():
    # Minimal article shape used by build_user_message
    return {
        "ai": [{"title": "x", "link": "https://a", "source": "s", "content": "ai body"}],
        "national": [{"title": "y", "link": "https://b", "source": "s", "content": "nat body"}],
        "international": [{"title": "z", "link": "https://c", "source": "s", "content": "intl body"}],
    }


def _briefs_pool():
    return [{"title": "q", "link": "https://d", "source": "s", "content": "tech body", "category": "tech"}]


async def test_generate_happy_path_returns_briefing():
    calls = []

    async def fake_call(client, prompt: str) -> str:
        calls.append(prompt)
        return GOOD_JSON

    briefing = await generate(
        articles_by_panel=_articles(),
        briefs_pool=_briefs_pool(),
        weather={"temp_high": 70, "temp_low": 50, "conditions": "x", "sunrise": "6:00", "sunset": "8:00", "pollen": "low"},
        today="Saturday, April 18, 2026",
        volume="Vol. I · No. 108",
        call_llm=fake_call,
        client=None,
    )
    assert isinstance(briefing, Briefing)
    assert len(calls) == 1


async def test_generate_retries_once_on_validation_failure():
    bad = json.dumps({"date": "x"})  # missing required fields
    attempts = [bad, GOOD_JSON]
    seen_prompts: list[str] = []

    async def fake_call(client, prompt: str) -> str:
        seen_prompts.append(prompt)
        return attempts.pop(0)

    briefing = await generate(
        articles_by_panel=_articles(),
        briefs_pool=_briefs_pool(),
        weather={"temp_high": 70, "temp_low": 50, "conditions": "x", "sunrise": "6:00", "sunset": "8:00", "pollen": "low"},
        today="Saturday, April 18, 2026",
        volume="Vol. I · No. 108",
        call_llm=fake_call,
        client=None,
    )
    assert isinstance(briefing, Briefing)
    assert len(seen_prompts) == 2
    # Second prompt must mention the previous failure
    assert "Previous attempt failed validation" in seen_prompts[1]


async def test_generate_raises_on_double_failure():
    bad = json.dumps({"date": "x"})

    async def fake_call(client, prompt: str) -> str:
        return bad

    with pytest.raises(GeneratorFailure):
        await generate(
            articles_by_panel=_articles(),
            briefs_pool=_briefs_pool(),
            weather={"temp_high": 70, "temp_low": 50, "conditions": "x", "sunrise": "6:00", "sunset": "8:00", "pollen": "low"},
            today="Saturday, April 18, 2026",
            volume="Vol. I · No. 108",
            call_llm=fake_call,
            client=None,
        )


def test_build_user_message_includes_articles_and_schema():
    msg = build_user_message(
        articles_by_panel=_articles(),
        briefs_pool=_briefs_pool(),
        weather={"temp_high": 70, "temp_low": 50, "conditions": "x", "sunrise": "6:00", "sunset": "8:00", "pollen": "low"},
        today="Saturday, April 18, 2026",
        volume="Vol. I · No. 108",
    )
    assert "Saturday, April 18, 2026" in msg
    assert "Vol. I · No. 108" in msg
    assert "ai body" in msg
    assert "tech body" in msg
    # Pydantic schema reference
    assert "panels" in msg
