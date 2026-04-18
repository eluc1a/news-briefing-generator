import pytest

from jina_clone.summarizer.providers import parse_json_response


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
