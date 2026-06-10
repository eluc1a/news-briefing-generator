import json
from datetime import datetime, timezone

from jina_clone.briefing.feed import (
    FEED_MAX_ENTRIES,
    publish_digest,
    publish_fallback,
    rebuild_feed,
)
from jina_clone.briefing.schema import DigestItem, SlackDigest

GEN_AT = datetime(2026, 6, 9, 8, 45, tzinfo=timezone.utc)
BASE = "https://feeds.example.com/ai-digest"


def _digest() -> SlackDigest:
    return SlackDigest(
        lead="Big day for agents & <tools>.",
        items=[
            DigestItem(url="https://a?x=1&y=2", title="T & A <tag>", blurb="b1"),
            DigestItem(url="https://b", title="Plain", blurb="b2"),
        ],
    )


def _publish(tmp_path, digest=None):
    return publish_digest(
        digest or _digest(),
        out_dir=tmp_path, base_url=BASE,
        iso_date="2026-06-09", edition="morning",
        edition_label="Morning", date_label="Tue Jun 9",
        generated_at=GEN_AT,
    )


def _record(iso_date: str, edition: str) -> dict:
    """A minimal degraded record, for rebuild-by-scan tests."""
    return {
        "date": iso_date, "edition": edition,
        "edition_label": edition.title(), "date_label": iso_date,
        "generated_at": GEN_AT.isoformat(), "degraded": True,
        "digest": None,
        "headlines": [{"link": "https://x", "title": "t"}],
    }


def test_publish_digest_writes_all_outputs(tmp_path):
    page = _publish(tmp_path)
    assert page == tmp_path / "2026-06-09-morning.html"
    assert (tmp_path / "2026-06-09-morning.json").exists()
    feed = (tmp_path / "feed.xml").read_text()
    assert "<title>AI/ML Morning Digest — Tue Jun 9</title>" in feed
    assert (
        '<guid isPermaLink="true">'
        f"{BASE}/2026-06-09-morning.html</guid>"
    ) in feed
    assert "<pubDate>Tue, 09 Jun 2026 08:45:00 +0000</pubDate>" in feed


def test_page_html_escapes_and_links(tmp_path):
    page = _publish(tmp_path).read_text()
    assert "T &amp; A &lt;tag&gt;" in page
    assert "<tag>" not in page
    assert '<a href="https://a?x=1&amp;y=2">' in page
    assert "Big day for agents &amp; &lt;tools&gt;." in page
    assert "Generated 2026-06-09 08:45 UTC" in page


def test_feed_description_is_cdata_with_body(tmp_path):
    _publish(tmp_path)
    feed = (tmp_path / "feed.xml").read_text()
    assert "<description><![CDATA[" in feed
    assert "Big day for agents &amp; &lt;tools&gt;." in feed


def test_publish_fallback_degraded_caps_and_defaults(tmp_path):
    articles = [{"link": f"https://x/{i}", "title": f"t{i}"} for i in range(8)]
    articles.append({"link": None, "title": "no link"})
    articles.append({"link": "https://x/notitle", "title": None})
    articles += [{"link": f"https://y/{i}", "title": f"u{i}"} for i in range(5)]
    page = publish_fallback(
        articles,
        out_dir=tmp_path, base_url=BASE,
        iso_date="2026-06-09", edition="afternoon",
        edition_label="Afternoon", date_label="Tue Jun 9",
        generated_at=GEN_AT,
    ).read_text()
    assert "LLM digest unavailable" in page
    assert '<a href="https://x/7">t7</a>' in page
    assert "no link" not in page                              # linkless skipped
    assert '<a href="https://x/notitle">https://x/notitle</a>' in page
    assert "https://y/0" not in page                          # capped at 10 slots


def test_rebuild_orders_newest_first_and_caps(tmp_path):
    for day in range(1, 13):                  # 12 days × 2 editions = 24 records
        for edition in ("morning", "afternoon"):
            iso = f"2026-06-{day:02d}"
            (tmp_path / f"{iso}-{edition}.json").write_text(
                json.dumps(_record(iso, edition))
            )
    rebuild_feed(tmp_path, base_url=BASE)
    feed = (tmp_path / "feed.xml").read_text()
    assert feed.count("<item>") == FEED_MAX_ENTRIES
    # newest first; afternoon outranks morning within a day
    assert feed.index("2026-06-12-afternoon.html") < feed.index("2026-06-12-morning.html")
    # oldest two days fall off the 20-entry cap
    assert "2026-06-02" not in feed
    assert "2026-06-01" not in feed


def test_rebuild_ignores_foreign_files(tmp_path):
    (tmp_path / "feed.xml").write_text("old")
    (tmp_path / "notes.json").write_text("{}")
    (tmp_path / "2026-06-09-morning.json").write_text(
        json.dumps(_record("2026-06-09", "morning"))
    )
    rebuild_feed(tmp_path, base_url=BASE)
    feed = (tmp_path / "feed.xml").read_text()
    assert feed.count("<item>") == 1
    assert "old" not in feed
