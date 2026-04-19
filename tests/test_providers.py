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
        api_keys=api_keys,
    )


def test_build_provider_requires_matching_api_key():
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        build_provider(_settings("claude", {}))


def test_build_provider_rejects_unknown_provider():
    with pytest.raises(ValueError, match="Unknown provider"):
        build_provider(_settings("banana", {}))


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
