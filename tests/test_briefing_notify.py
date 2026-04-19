from unittest.mock import MagicMock, patch

from jina_clone.briefing.notify import notify_failure, notify_printed


def test_notify_printed_no_topic_is_noop():
    with patch("jina_clone.briefing.notify.httpx.post") as post:
        notify_printed(topic=None)
        post.assert_not_called()


def test_notify_printed_posts_to_ntfy():
    with patch("jina_clone.briefing.notify.httpx.post") as post:
        notify_printed(topic="fox-briefings", pages=2)
        post.assert_called_once()
        url = post.call_args[0][0]
        assert url == "https://ntfy.sh/fox-briefings"
        headers = post.call_args.kwargs["headers"]
        assert headers["Title"] == "The Morning Fox"
        assert "high" not in headers.get("Priority", "").lower()


def test_notify_failure_uses_high_priority():
    with patch("jina_clone.briefing.notify.httpx.post") as post:
        notify_failure(topic="fox-briefings", reason="printer offline")
        post.assert_called_once()
        headers = post.call_args.kwargs["headers"]
        assert headers["Priority"] == "high"
        body = post.call_args.kwargs["data"]
        assert b"printer offline" in body


def test_notify_failure_no_topic_is_noop():
    with patch("jina_clone.briefing.notify.httpx.post") as post:
        notify_failure(topic=None, reason="x")
        post.assert_not_called()
