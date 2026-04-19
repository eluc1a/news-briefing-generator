from pathlib import Path

import pytest

from jina_clone.briefing.config import (
    BriefingCategories,
    PanelDef,
    load_briefing_categories,
)


CONFIG = Path("config/briefing_categories.yaml")


def test_load_returns_three_panels():
    cats = load_briefing_categories(CONFIG)
    assert isinstance(cats, BriefingCategories)
    assert len(cats.panels) == 3
    assert [p.key for p in cats.panels] == ["ai", "national", "international"]


def test_all_referenced_categories_are_unique():
    cats = load_briefing_categories(CONFIG)
    seen: set[str] = set()
    for panel in cats.panels:
        for c in panel.categories:
            assert c not in seen, f"category {c!r} appears in multiple panels"
            seen.add(c)
    for c in cats.briefs_categories:
        assert c not in seen, f"brief category {c!r} also assigned to a panel"
        seen.add(c)


def test_min_articles_total_loaded():
    cats = load_briefing_categories(CONFIG)
    assert cats.min_articles_total == 8


def test_panel_for_category_lookup():
    cats = load_briefing_categories(CONFIG)
    assert cats.panel_for_category("ai") == "ai"
    assert cats.panel_for_category("us_local_news") == "national"
    assert cats.panel_for_category("regional_international_news") == "international"
    assert cats.panel_for_category("cybersecurity") is None  # in briefs pool, no panel


def test_all_categories_returns_union():
    cats = load_briefing_categories(CONFIG)
    all_cats = cats.all_categories()
    assert "ai" in all_cats
    assert "cybersecurity" in all_cats
    # Should include both panel and briefs categories
    assert len(all_cats) >= 12


def test_unknown_panel_key_in_yaml_rejected(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "panels:\n"
        "  - key: ai\n"
        "    title: AI\n"
        "    categories: [ai]\n"
        "briefs:\n"
        "  categories: [tech]\n"
    )
    # Missing min_articles_total — should raise
    with pytest.raises((KeyError, ValueError)):
        load_briefing_categories(bad)
