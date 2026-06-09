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

    def __init__(self, rows=None, gen_fails=False, post_fails=False):
        self.rows = _rows() if rows is None else rows
        self.gen_fails = gen_fails
        self.post_fails = post_fails
        self.fetch_kwargs: dict = {}
        self.posted: list[tuple] = []
        self.notified: list[dict] = []

    async def fetch(self, pool, **kwargs):
        self.fetch_kwargs = kwargs
        return self.rows

    async def generate(self, *, articles, edition_label):
        if self.gen_fails:
            raise GeneratorFailure("claude -p exited 1")
        return _digest()

    def format_digest(self, digest, *, edition_label, date_label):
        return {"text": "digest"}

    def format_fallback(self, articles, *, edition_label, date_label):
        return {"text": "fallback"}

    def post(self, url, payload):
        if self.post_fails:
            raise RuntimeError("webhook down")
        self.posted.append((url, payload))

    def notify_failure(self, **kwargs):
        self.notified.append(kwargs)

    async def run(self):
        return await run_slack_digest(
            None,
            webhook_url="https://hooks.slack.com/services/X",
            window_hours=7.75,
            edition_label="Afternoon",
            date_label="Tue Jun 9",
            title="AI/ML Slack Digest",
            ntfy_topic="fox-briefings",
            source_caps={"arXiv cs.AI": 2},
            fetch_articles=self.fetch,
            generate_digest=self.generate,
            format_digest=self.format_digest,
            format_fallback=self.format_fallback,
            post=self.post,
            notify_failure=self.notify_failure,
        )


async def test_happy_path_posts_digest_no_notify():
    h = Harness()
    result = await h.run()
    assert h.posted == [
        ("https://hooks.slack.com/services/X", {"text": "digest"})
    ]
    assert h.notified == []
    assert result == {"degraded": False, "article_count": 2}


async def test_fetch_receives_window_caps_and_category():
    h = Harness()
    await h.run()
    assert h.fetch_kwargs["categories"] == ["ai"]
    assert h.fetch_kwargs["since_hours"] == 7.75
    assert h.fetch_kwargs["limit"] == 40
    assert h.fetch_kwargs["source_caps"] == {"arXiv cs.AI": 2}


async def test_llm_failure_posts_fallback_and_notifies():
    h = Harness(gen_fails=True)
    result = await h.run()
    assert h.posted == [
        ("https://hooks.slack.com/services/X", {"text": "fallback"})
    ]
    assert len(h.notified) == 1
    assert "fallback" in h.notified[0]["reason"]
    assert result == {"degraded": True, "article_count": 2}


async def test_zero_articles_skips_post_and_notify():
    h = Harness(rows=[])
    result = await h.run()
    assert result is None
    assert h.posted == []
    assert h.notified == []


async def test_webhook_failure_notifies_and_raises():
    h = Harness(post_fails=True)
    with pytest.raises(RuntimeError):
        await h.run()
    assert len(h.notified) == 1
    assert "webhook" in h.notified[0]["reason"].lower()
