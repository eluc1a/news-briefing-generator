import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from jina_clone.briefing.schema import Briefing


FIXTURE = Path("jina_clone/briefing/fixtures/sample_briefing.json")


def test_sample_fixture_validates():
    raw = FIXTURE.read_text()
    briefing = Briefing.model_validate_json(raw)
    assert briefing.lead.headline
    assert len(briefing.panels) == 4
    assert {p.section for p in briefing.panels} == {
        "AI & Technology", "National", "Economy & Markets", "International",
    }
    # Each panel now has a lede_headline, lede_body, and 3-4 `also` items.
    for panel in briefing.panels:
        assert panel.lede_headline
        assert panel.lede_body
        assert len(panel.also) == 3
        for item in panel.also:
            assert item.headline
            assert item.body
    assert 5 <= len(briefing.briefs) <= 6


def test_three_panels_rejected():
    raw = FIXTURE.read_text()
    data = json.loads(raw)
    data["panels"] = data["panels"][:3]
    with pytest.raises(ValidationError):
        Briefing.model_validate(data)


def test_briefs_too_few_rejected():
    raw = FIXTURE.read_text()
    data = json.loads(raw)
    data["briefs"] = data["briefs"][:4]  # below new floor of 5
    with pytest.raises(ValidationError):
        Briefing.model_validate(data)


def test_briefs_too_many_rejected():
    raw = FIXTURE.read_text()
    data = json.loads(raw)
    # Double the briefs to push above the new ceiling of 7.
    data["briefs"] = (data["briefs"] * 2)[:7]
    with pytest.raises(ValidationError):
        Briefing.model_validate(data)


def test_invalid_section_label_rejected():
    raw = FIXTURE.read_text()
    data = json.loads(raw)
    data["panels"][0]["section"] = "Markets"
    with pytest.raises(ValidationError):
        Briefing.model_validate(data)


def test_panel_missing_also_rejected():
    raw = FIXTURE.read_text()
    data = json.loads(raw)
    del data["panels"][0]["also"]
    with pytest.raises(ValidationError):
        Briefing.model_validate(data)


def test_panel_also_too_few_rejected():
    raw = FIXTURE.read_text()
    data = json.loads(raw)
    data["panels"][0]["also"] = data["panels"][0]["also"][:2]
    with pytest.raises(ValidationError):
        Briefing.model_validate(data)


def test_panel_also_too_many_rejected():
    raw = FIXTURE.read_text()
    data = json.loads(raw)
    # Push to 4 `also` items — must now fail (new ceiling is 3).
    first_item = data["panels"][0]["also"][0]
    data["panels"][0]["also"] = data["panels"][0]["also"] + [first_item]
    with pytest.raises(ValidationError):
        Briefing.model_validate(data)


def test_briefing_requires_title():
    raw = FIXTURE.read_text()
    data = json.loads(raw)
    del data["title"]
    with pytest.raises(ValidationError):
        Briefing.model_validate(data)


def test_briefing_title_round_trips():
    raw = FIXTURE.read_text()
    data = json.loads(raw)
    data["title"] = "The Evening Fox"
    b = Briefing.model_validate(data)
    assert b.title == "The Evening Fox"


def test_weather_requires_daylight_not_pollen():
    """Weather strip gained `daylight`; `pollen` is no longer a field."""
    raw = FIXTURE.read_text()
    data = json.loads(raw)
    # Fixture should already have daylight (added in this task).
    assert "daylight" in data["weather"]
    assert "pollen" not in data["weather"]
    b = Briefing.model_validate(data)
    assert b.weather.daylight
    # Adding pollen back should not break (Pydantic ignores unknown by default),
    # but removing daylight must fail:
    data_bad = json.loads(raw)
    del data_bad["weather"]["daylight"]
    with pytest.raises(ValidationError):
        Briefing.model_validate(data_bad)


def test_briefing_requires_hourly_forecast():
    raw = FIXTURE.read_text()
    data = json.loads(raw)
    assert "hourly" in data
    assert len(data["hourly"]["slots"]) == 4
    b = Briefing.model_validate(data)
    assert len(b.hourly.slots) == 4
    assert b.hourly.slots[0].time_label  # e.g. "8am"

    # Exactly 4 slots — not 3, not 5.
    data_bad = json.loads(raw)
    data_bad["hourly"]["slots"] = data_bad["hourly"]["slots"][:3]
    with pytest.raises(ValidationError):
        Briefing.model_validate(data_bad)

    data_bad2 = json.loads(raw)
    extra_slot = data_bad2["hourly"]["slots"][0]
    data_bad2["hourly"]["slots"] = data_bad2["hourly"]["slots"] + [extra_slot]
    with pytest.raises(ValidationError):
        Briefing.model_validate(data_bad2)
