from pathlib import Path

import pytest

from jina_clone.briefing.generator import GeneratorFailure
from jina_clone.briefing.schema import DigestItem, SlackDigest
from jina_clone.jobs.slack_digest import run_slack_digest


def _rows():
    return [
        {"title": "t1", "link": "https://a", "source": "S1", "content": "c1"},
        {"title": "t2", "link": "https://b", "source": "S2", "content": "c2"},
    ]


def _digest():
    return SlackDigest(
        lead="L",
        items=[DigestItem(url="https://a", title="T", blurb="B")],
    )


class Harness:
    """Injected fakes + recorders for run_slack_digest."""

    def __init__(self, rows=None, gen_fails=False, publish_fails=False):
        self.rows = _rows() if rows is None else rows
        self.gen_fails = gen_fails
        self.publish_fails = publish_fails
        self.fetch_kwargs: dict = {}
        self.published: list[tuple] = []
        self.notified: list[dict] = []

    async def fetch(self, pool, **kwargs):
        self.fetch_kwargs = kwargs
        return self.rows

    async def generate(self, *, articles, edition_label):
        if self.gen_fails:
            raise GeneratorFailure("claude -p exited 1")
        return _digest()

    def publish(self, digest):
        if self.publish_fails:
            raise OSError("disk full")
        self.published.append(("digest", digest))
        return Path("/tmp/2026-06-09-afternoon.html")

    def publish_fallback(self, articles):
        if self.publish_fails:
            raise OSError("disk full")
        self.published.append(("fallback", articles))
        return Path("/tmp/2026-06-09-afternoon.html")

    def notify_failure(self, **kwargs):
        self.notified.append(kwargs)

    async def run(self):
        return await run_slack_digest(
            None,
            window_hours=7.75,
            edition_label="Afternoon",
            title="AI/ML Slack Digest",
            ntfy_topic="fox-briefings",
            source_caps={"arXiv cs.AI": 2},
            fetch_articles=self.fetch,
            generate_digest=self.generate,
            publish=self.publish,
            publish_fallback=self.publish_fallback,
            notify_failure=self.notify_failure,
        )


async def test_happy_path_publishes_digest_no_notify():
    h = Harness()
    result = await h.run()
    assert h.published == [("digest", _digest())]
    assert h.notified == []
    assert result == {"degraded": False, "article_count": 2}


async def test_fetch_receives_window_caps_and_category():
    h = Harness()
    await h.run()
    assert h.fetch_kwargs["categories"] == ["ai"]
    assert h.fetch_kwargs["since_hours"] == 7.75
    assert h.fetch_kwargs["limit"] == 40
    assert h.fetch_kwargs["source_caps"] == {"arXiv cs.AI": 2}


async def test_llm_failure_publishes_fallback_and_notifies():
    h = Harness(gen_fails=True)
    result = await h.run()
    assert h.published == [("fallback", _rows())]
    assert len(h.notified) == 1
    assert "fallback" in h.notified[0]["reason"]
    assert result == {"degraded": True, "article_count": 2}


async def test_zero_articles_skips_publish_and_notify():
    h = Harness(rows=[])
    result = await h.run()
    assert result is None
    assert h.published == []
    assert h.notified == []


async def test_publish_failure_notifies_and_raises():
    h = Harness(publish_fails=True)
    with pytest.raises(OSError):
        await h.run()
    assert len(h.notified) == 1
    assert "publish" in h.notified[0]["reason"].lower()


async def test_degraded_plus_publish_failure_notifies_publish_only():
    h = Harness(gen_fails=True, publish_fails=True)
    with pytest.raises(OSError):
        await h.run()
    assert len(h.notified) == 1
    assert "publish" in h.notified[0]["reason"].lower()
    assert "fallback" not in h.notified[0]["reason"].lower()
