from pathlib import Path

from jina_clone.briefing.markdown import briefing_to_markdown
from jina_clone.briefing.schema import Briefing


FIXTURE = Path("jina_clone/briefing/fixtures/sample_briefing.json")


def test_markdown_contains_all_sections():
    briefing = Briefing.model_validate_json(FIXTURE.read_text())
    md = briefing_to_markdown(briefing)
    assert "# " in md  # title
    assert "## Lead:" in md
    assert "## AI & Technology" in md
    assert "## National" in md
    assert "## International" in md
    assert "## Briefs" in md
    assert "## Data point" in md
    assert "## On this day" in md
    assert briefing.lead.headline in md
    assert briefing.pull_quote in md
    # All briefs should appear by topic
    for b in briefing.briefs:
        assert b.topic in md


def test_markdown_header_uses_briefing_title():
    briefing = Briefing.model_validate_json(FIXTURE.read_text())
    md = briefing_to_markdown(briefing)
    assert f"# {briefing.date} — {briefing.title} · {briefing.volume}" in md


def test_markdown_header_flips_for_evening_edition():
    import json
    data = json.loads(FIXTURE.read_text())
    data["title"] = "The Evening Fox"
    briefing = Briefing.model_validate(data)
    md = briefing_to_markdown(briefing)
    assert "The Evening Fox" in md
    assert "Morning Fox" not in md
