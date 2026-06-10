from pathlib import Path

import pytest

from jina_clone.config import Source, load_sources, Settings


def test_load_sources_parses_rss_and_scrape(tmp_path):
    yaml_path = tmp_path / "sources.yaml"
    yaml_path.write_text(
        "sources:\n"
        "  - name: Foo\n"
        "    type: rss\n"
        "    url: https://foo.example/feed\n"
        "    category: ai\n"
        "  - name: Bar\n"
        "    type: scrape\n"
        "    url: https://bar.example\n"
        "    link_selector: a.article\n"
        "    category: ai\n"
    )
    sources = load_sources(yaml_path)
    assert len(sources) == 2
    assert sources[0] == Source(name="Foo", type="rss", url="https://foo.example/feed",
                                category="ai", link_selector=None)
    assert sources[1].link_selector == "a.article"


def test_load_sources_rejects_unknown_type(tmp_path):
    yaml_path = tmp_path / "sources.yaml"
    yaml_path.write_text(
        "sources:\n  - name: Foo\n    type: banana\n    url: x\n    category: ai\n"
    )
    with pytest.raises(ValueError, match="Unknown source type"):
        load_sources(yaml_path)


def test_load_sources_requires_link_selector_for_scrape(tmp_path):
    yaml_path = tmp_path / "sources.yaml"
    yaml_path.write_text(
        "sources:\n  - name: Foo\n    type: scrape\n    url: x\n    category: ai\n"
    )
    with pytest.raises(ValueError, match="link_selector"):
        load_sources(yaml_path)


def test_settings_from_env_does_not_require_api_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://dummy")
    settings = Settings.from_env()
    assert settings.llm_provider == "gemini"
    assert settings.api_keys == {}


def test_settings_from_env_rejects_unknown_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "banana")
    monkeypatch.setenv("DATABASE_URL", "postgresql://dummy")
    with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
        Settings.from_env()


def test_settings_briefing_defaults(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x/y")
    monkeypatch.setenv("LLM_PROVIDER", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.delenv("NTFY_TOPIC", raising=False)
    monkeypatch.delenv("PRINT_QUEUE", raising=False)
    monkeypatch.delenv("BRIEFING_CATEGORIES_FILE", raising=False)
    monkeypatch.delenv("BRIEFINGS_DIR", raising=False)

    from jina_clone.config import Settings
    s = Settings.from_env()

    assert s.print_queue == "brother"
    assert s.ntfy_topic is None
    assert str(s.briefing_categories_file).endswith("briefing_categories.yaml")
    assert str(s.briefings_dir).endswith("briefings")


def test_settings_briefing_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x/y")
    monkeypatch.setenv("LLM_PROVIDER", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("NTFY_TOPIC", "fox-briefings")
    monkeypatch.setenv("PRINT_QUEUE", "brother-back")
    cats = tmp_path / "cats.yaml"
    cats.write_text("panels: []\nbriefs: {categories: []}\nmin_articles_total: 1\n")
    monkeypatch.setenv("BRIEFING_CATEGORIES_FILE", str(cats))
    monkeypatch.setenv("BRIEFINGS_DIR", str(tmp_path / "briefings"))

    from jina_clone.config import Settings
    s = Settings.from_env()

    assert s.ntfy_topic == "fox-briefings"
    assert s.print_queue == "brother-back"
    assert s.briefing_categories_file == cats
    assert s.briefings_dir == tmp_path / "briefings"


def test_settings_feed_delivery(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("LLM_PROVIDER", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.delenv("FEED_BASE_URL", raising=False)
    monkeypatch.delenv("FEED_OUTPUT_DIR", raising=False)
    from jina_clone.config import Settings

    s = Settings.from_env()
    assert s.feed_base_url is None
    assert s.feed_output_dir == Path("feeds/ai-digest")

    monkeypatch.setenv("FEED_BASE_URL", "https://feeds.elucia.com/ai-digest")
    monkeypatch.setenv("FEED_OUTPUT_DIR", "/tmp/feeds")
    s = Settings.from_env()
    assert s.feed_base_url == "https://feeds.elucia.com/ai-digest"
    assert s.feed_output_dir == Path("/tmp/feeds")
