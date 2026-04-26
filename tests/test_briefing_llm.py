import pytest

from jina_clone.briefing.llm import (
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_OPENROUTER_MODEL,
    AnthropicBriefingLLM,
    OpenRouterBriefingLLM,
    build_briefing_llm,
)
from jina_clone.config import Settings


def _settings(provider: str, api_keys: dict, *, model: str | None = None) -> Settings:
    return Settings(
        database_url="postgresql://dummy",
        sources_file=None,
        summaries_dir=None,
        fetch_concurrency=1,
        fetch_delay_seconds=0,
        fetch_window_hours=24,
        request_timeout=1,
        max_text_length=1,
        llm_provider=provider,
        llm_model=model,
        summary_token_cap=850000,
        summary_window_hours=24,
        briefing_categories_file=None,
        briefings_dir=None,
        print_queue="brother",
        ntfy_topic=None,
        api_keys=api_keys,
    )


def test_build_briefing_llm_claude_default():
    llm = build_briefing_llm(_settings("claude", {"ANTHROPIC_API_KEY": "k"}))
    assert isinstance(llm, AnthropicBriefingLLM)
    assert llm.name == "claude"
    assert llm.model == DEFAULT_ANTHROPIC_MODEL


def test_build_briefing_llm_claude_model_override():
    llm = build_briefing_llm(
        _settings("claude", {"ANTHROPIC_API_KEY": "k"}, model="claude-opus-4-7")
    )
    assert llm.model == "claude-opus-4-7"


def test_build_briefing_llm_openrouter_default():
    llm = build_briefing_llm(_settings("openrouter", {"OPENROUTER_API_KEY": "k"}))
    assert isinstance(llm, OpenRouterBriefingLLM)
    assert llm.name == "openrouter"
    assert llm.model == DEFAULT_OPENROUTER_MODEL
    assert llm._provider_routing is None
    assert llm._extra_headers == {}


def test_build_briefing_llm_openrouter_with_routing():
    settings = _settings("openrouter", {"OPENROUTER_API_KEY": "k"})
    settings.openrouter_provider_order = ["deepseek"]
    settings.openrouter_allow_fallbacks = False
    settings.openrouter_app_url = "https://example.com"
    settings.openrouter_app_title = "Fox"
    llm = build_briefing_llm(settings)
    assert llm._provider_routing == {"order": ["deepseek"], "allow_fallbacks": False}
    assert llm._extra_headers == {
        "HTTP-Referer": "https://example.com",
        "X-OpenRouter-Title": "Fox",
    }


def test_build_briefing_llm_openrouter_model_override():
    settings = _settings(
        "openrouter",
        {"OPENROUTER_API_KEY": "k"},
        model="anthropic/claude-sonnet-4-6",
    )
    llm = build_briefing_llm(settings)
    assert llm.model == "anthropic/claude-sonnet-4-6"


@pytest.mark.parametrize("unsupported", ["openai", "gemini", "banana"])
def test_build_briefing_llm_rejects_unsupported_provider(unsupported):
    with pytest.raises(ValueError, match="briefing supports"):
        build_briefing_llm(_settings(unsupported, {}))


def test_build_briefing_llm_missing_anthropic_key():
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        build_briefing_llm(_settings("claude", {}))


def test_build_briefing_llm_missing_openrouter_key():
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        build_briefing_llm(_settings("openrouter", {}))
