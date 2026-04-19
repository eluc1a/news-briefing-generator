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
    assert len(briefing.panels) == 3
    assert {p.section for p in briefing.panels} == {
        "AI & Technology", "National", "International",
    }
    assert 6 <= len(briefing.briefs) <= 9


def test_two_panels_rejected():
    raw = FIXTURE.read_text()
    data = json.loads(raw)
    data["panels"] = data["panels"][:2]
    with pytest.raises(ValidationError):
        Briefing.model_validate(data)


def test_briefs_too_few_rejected():
    raw = FIXTURE.read_text()
    data = json.loads(raw)
    data["briefs"] = data["briefs"][:5]
    with pytest.raises(ValidationError):
        Briefing.model_validate(data)


def test_invalid_section_label_rejected():
    raw = FIXTURE.read_text()
    data = json.loads(raw)
    data["panels"][0]["section"] = "Markets"
    with pytest.raises(ValidationError):
        Briefing.model_validate(data)
