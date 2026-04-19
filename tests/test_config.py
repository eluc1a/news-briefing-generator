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
