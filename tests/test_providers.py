import pytest

from jina_clone.config import Settings
from jina_clone.summarizer.providers import build_provider, parse_json_response


def _settings(provider: str, api_keys: dict) -> Settings:
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
        llm_model=None,
        summary_token_cap=850000,
        summary_window_hours=24,
        briefing_categories_file=None,
        briefings_dir=None,
        print_queue="brother",
        ntfy_topic=None,
        api_keys=api_keys,
    )


def test_build_provider_requires_matching_api_key():
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        build_provider(_settings("claude", {}))


def test_build_provider_rejects_unknown_provider():
    with pytest.raises(ValueError, match="Unknown provider"):
        build_provider(_settings("banana", {}))


def test_build_provider_openrouter_requires_api_key():
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        build_provider(_settings("openrouter", {}))


def test_build_provider_openrouter_without_routing_omits_provider_field():
    p = build_provider(_settings("openrouter", {"OPENROUTER_API_KEY": "k"}))
    assert p.name == "openrouter"
    assert p.model == "deepseek/deepseek-v4-pro"
    assert p._provider_routing is None
    assert p._extra_headers == {}


def test_build_provider_openrouter_pins_to_configured_upstream():
    settings = _settings("openrouter", {"OPENROUTER_API_KEY": "k"})
    settings.openrouter_provider_order = ["deepseek"]
    settings.openrouter_allow_fallbacks = False
    settings.openrouter_app_url = "https://example.com"
    settings.openrouter_app_title = "MyApp"
    p = build_provider(settings)
    assert p._provider_routing == {"order": ["deepseek"], "allow_fallbacks": False}
    assert p._extra_headers == {
        "HTTP-Referer": "https://example.com",
        "X-OpenRouter-Title": "MyApp",
    }


def test_build_provider_openrouter_respects_model_override():
    settings = _settings("openrouter", {"OPENROUTER_API_KEY": "k"})
    settings.llm_model = "anthropic/claude-sonnet-4-5"
    p = build_provider(settings)
    assert p.model == "anthropic/claude-sonnet-4-5"


def test_parse_json_response_happy_path():
    raw = '{"headline": "H", "body": "B"}'
    assert parse_json_response(raw) == {"headline": "H", "body": "B"}


def test_parse_json_response_with_leading_and_trailing_whitespace():
    raw = '\n  {"headline": "H", "body": "B"}  \n'
    assert parse_json_response(raw) == {"headline": "H", "body": "B"}


def test_parse_json_response_strips_code_fences():
    raw = '```json\n{"headline": "H", "body": "B"}\n```'
    assert parse_json_response(raw) == {"headline": "H", "body": "B"}


def test_parse_json_response_raises_on_missing_keys():
    with pytest.raises(ValueError, match="missing"):
        parse_json_response('{"headline": "H"}')


def test_parse_json_response_raises_on_invalid_json():
    with pytest.raises(ValueError, match="JSON"):
        parse_json_response("not json")
