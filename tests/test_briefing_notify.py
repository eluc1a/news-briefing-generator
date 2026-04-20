from unittest.mock import patch

from jina_clone.briefing.notify import notify_failure, notify_printed


def test_notify_printed_no_topic_is_noop():
    with patch("jina_clone.briefing.notify.httpx.post") as post:
        notify_printed(topic=None, title="The Morning Fox")
        post.assert_not_called()


def test_notify_printed_posts_morning_title():
    with patch("jina_clone.briefing.notify.httpx.post") as post:
        notify_printed(topic="fox-briefings", title="The Morning Fox", pages=2)
        post.assert_called_once()
        url = post.call_args[0][0]
        assert url == "https://ntfy.sh/fox-briefings"
        headers = post.call_args.kwargs["headers"]
        assert headers["Title"] == "The Morning Fox"
        body = post.call_args.kwargs["data"]
        assert b"The Morning Fox briefing printed" in body


def test_notify_printed_posts_evening_title():
    with patch("jina_clone.briefing.notify.httpx.post") as post:
        notify_printed(topic="fox-briefings", title="The Evening Fox", pages=2)
        headers = post.call_args.kwargs["headers"]
        assert headers["Title"] == "The Evening Fox"
        body = post.call_args.kwargs["data"]
        assert b"The Evening Fox briefing printed" in body


def test_notify_failure_uses_high_priority_and_title():
    with patch("jina_clone.briefing.notify.httpx.post") as post:
        notify_failure(
            topic="fox-briefings",
            title="The Evening Fox",
            reason="printer offline",
        )
        headers = post.call_args.kwargs["headers"]
        assert headers["Priority"] == "high"
        assert headers["Title"] == "The Evening Fox — failure"
        body = post.call_args.kwargs["data"]
        assert b"printer offline" in body


def test_notify_failure_no_topic_is_noop():
    with patch("jina_clone.briefing.notify.httpx.post") as post:
        notify_failure(topic=None, title="The Morning Fox", reason="x")
        post.assert_not_called()
