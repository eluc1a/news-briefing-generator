from pathlib import Path

import pytest

from jina_clone.briefing.config import (
    BriefingConfig,
    BriefsDef,
    SectionDef,
    load_briefing_config,
)


CONFIG = Path("config/briefing_categories.yaml")


def test_load_returns_four_sections():
    cfg = load_briefing_config(CONFIG)
    assert isinstance(cfg, BriefingConfig)
    assert len(cfg.sections) == 4
    assert [s.key for s in cfg.sections] == [
        "national", "economy", "ai", "international",
    ]


def test_ai_section_is_narrowed_to_ai_category_only():
    cfg = load_briefing_config(CONFIG)
    ai = next(s for s in cfg.sections if s.key == "ai")
    assert ai.categories == ("ai",)


def test_each_section_has_a_limit():
    cfg = load_briefing_config(CONFIG)
    for s in cfg.sections:
        assert s.limit > 0


def test_briefs_loaded():
    cfg = load_briefing_config(CONFIG)
    assert isinstance(cfg.briefs, BriefsDef)
    assert "cybersecurity" in cfg.briefs.categories
    assert cfg.briefs.limit > 0


def test_top_level_knobs():
    cfg = load_briefing_config(CONFIG)
    assert cfg.per_source_cap == 5
    assert cfg.front_matter_top_per_section == 5
    assert cfg.min_articles_total == 8


def test_categories_are_unique_across_sections_and_briefs():
    cfg = load_briefing_config(CONFIG)
    seen: set[str] = set()
    for s in cfg.sections:
        for c in s.categories:
            assert c not in seen, f"category {c!r} appears in multiple sections"
            seen.add(c)
    for c in cfg.briefs.categories:
        assert c not in seen, f"brief category {c!r} also assigned to a section"
        seen.add(c)


def test_missing_min_articles_total_rejected(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "sections:\n"
        "  - key: ai\n"
        "    title: AI\n"
        "    categories: [ai]\n"
        "    limit: 40\n"
        "briefs:\n"
        "  categories: [tech]\n"
        "  limit: 50\n"
        "per_source_cap: 5\n"
        "front_matter_top_per_section: 5\n"
    )
    with pytest.raises((KeyError, ValueError)):
        load_briefing_config(bad)
