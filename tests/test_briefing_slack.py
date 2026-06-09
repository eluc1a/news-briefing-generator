from unittest.mock import patch

import httpx
import pytest

from jina_clone.briefing.schema import DigestItem, SlackDigest
from jina_clone.briefing.slack import (
    format_digest,
    format_headlines_fallback,
    post_webhook,
)


def _digest() -> SlackDigest:
    return SlackDigest(
        lead="Big day for agents.",
        items=[
            DigestItem(url="https://a", title="T & A <tag>", blurb="b1"),
            DigestItem(url="https://b", title="Plain", blurb="b2"),
        ],
    )


def test_format_digest_structure():
    payload = format_digest(
        _digest(), edition_label="Morning", date_label="Tue Jun 9",
    )
    assert payload["unfurl_links"] is False
    assert payload["unfurl_media"] is False
    text = payload["text"]
    assert text.startswith("*🤖 AI/ML Morning Digest — Tue Jun 9*")
    assert "Big day for agents." in text
    assert "• <https://b|Plain> — b2" in text


def test_format_digest_escapes_mrkdwn_specials():
    # Slack mrkdwn requires &, <, > escaped in text (else <tag> becomes
    # a broken link token). & must be replaced first.
    text = format_digest(
        _digest(), edition_label="Morning", date_label="Tue Jun 9",
    )["text"]
    assert "T &amp; A &lt;tag&gt;" in text
    assert "<tag>" not in text


def test_format_digest_escapes_url():
    digest = SlackDigest(
        lead="lead",
        items=[DigestItem(url="https://x?a=1&b=2", title="t", blurb="b")],
    )
    text = format_digest(
        digest, edition_label="Morning", date_label="Tue Jun 9",
    )["text"]
    assert "<https://x?a=1&amp;b=2|t>" in text


def test_fallback_caps_items_and_notes_degraded():
    articles = [
        {"link": f"https://x/{i}", "title": f"t{i}"} for i in range(15)
    ]
    payload = format_headlines_fallback(
        articles, edition_label="Afternoon", date_label="Tue Jun 9",
    )
    text = payload["text"]
    assert text.startswith("*🤖 AI/ML Afternoon Digest — Tue Jun 9*")
    assert "headlines only" in text
    assert "<https://x/9|t9>" in text
    assert "https://x/10" not in text  # capped at 10
    assert payload["unfurl_links"] is False


def test_fallback_handles_missing_title():
    payload = format_headlines_fallback(
        [{"link": "https://x", "title": None}],
        edition_label="Morning", date_label="Tue Jun 9",
    )
    assert "<https://x|https://x>" in payload["text"]


def test_fallback_skips_article_without_link():
    payload = format_headlines_fallback(
        [{"title": "t"}, {"link": "https://x", "title": "kept"}],
        edition_label="Morning", date_label="Tue Jun 9",
    )
    text = payload["text"]
    assert "<https://x|kept>" in text
    assert "• <|" not in text


def test_post_webhook_posts_json():
    with patch("jina_clone.briefing.slack.httpx.post") as post:
        post.return_value.raise_for_status.return_value = None
        post_webhook("https://hooks.slack.com/services/X", {"text": "hi"})
        post.assert_called_once()
        assert post.call_args.args[0] == "https://hooks.slack.com/services/X"
        assert post.call_args.kwargs["json"] == {"text": "hi"}


def test_post_webhook_raises_on_http_error():
    with patch("jina_clone.briefing.slack.httpx.post") as post:
        post.return_value.raise_for_status.side_effect = httpx.HTTPStatusError(
            "boom", request=None, response=None,
        )
        with pytest.raises(httpx.HTTPStatusError):
            post_webhook("https://hooks.slack.com/services/X", {"text": "hi"})
