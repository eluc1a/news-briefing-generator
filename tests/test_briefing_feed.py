import json
from datetime import datetime, timezone

from jina_clone.briefing.feed import (
    FEED_MAX_ENTRIES,
    publish_digest,
    publish_fallback,
    rebuild_feed,
    update_latest,
)
from jina_clone.briefing.schema import DigestItem, SlackDigest

GEN_AT = datetime(2026, 6, 9, 8, 45, tzinfo=timezone.utc)
BASE = "https://feeds.example.com/ai-digest"


def _digest() -> SlackDigest:
    return SlackDigest(
        lead="Big day for agents & <tools>.",
        items=[
            DigestItem(url="https://a?x=1&y=2", title="T & A <tag>", blurb="b1",
                       category="news", source="S&P <Wire>"),
            DigestItem(url="https://b", title="Plain", blurb="b2",
                       category="tool", source="S2"),
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


def test_page_html_newspaper_chrome(tmp_path):
    page = _publish(tmp_path).read_text()
    assert 'class="masthead-title"' in page
    assert "Bodoni Moda" in page
    assert "Morning Edition" in page          # dateline left
    assert "Tue Jun 9" in page                # dateline right
    assert "<ul>" not in page                 # stories are article blocks now
    assert page.count("<article") == 2


def test_page_html_category_labels_and_sources(tmp_path):
    page = _publish(tmp_path).read_text()
    assert '<span class="label label-news">news</span>' in page
    assert '<span class="label label-tool">tool</span>' in page
    assert ".label-news { background:" in page      # per-category colors
    assert '<span class="story-source">— S&amp;P &lt;Wire&gt;</span>' in page
    assert '<span class="story-source">— S2</span>' in page


def test_page_html_renders_items_without_category_or_source(tmp_path):
    # Records published before category/source existed must still render
    # (rebuild_feed revalidates old JSON records).
    digest = SlackDigest(
        lead="Old record.",
        items=[DigestItem(url="https://a", title="T", blurb="b")],
    )
    page = _publish(tmp_path, digest=digest).read_text()
    assert 'class="label' not in page
    assert 'class="story-source"' not in page
    assert '<a href="https://a">T</a>' in page


def test_publish_copies_fonts_next_to_pages(tmp_path):
    _publish(tmp_path)
    assert (tmp_path / "fonts" / "BodoniModa-Regular.ttf").exists()
    assert (tmp_path / "fonts" / "BodoniModa-Medium.ttf").exists()


def test_feed_description_is_cdata_with_body(tmp_path):
    _publish(tmp_path)
    feed = (tmp_path / "feed.xml").read_text()
    assert "<description><![CDATA[" in feed
    assert "Big day for agents &amp; &lt;tools&gt;." in feed


def test_feed_description_flattens_with_bare_source_urls(tmp_path):
    # Slack's /feed strips <ul>/<li> and <a>, so the feed description must
    # expose each source URL as bare text (Slack auto-links those) and use
    # no list markup. The rich <ul> stays on the HTML page only.
    _publish(tmp_path)
    feed = (tmp_path / "feed.xml").read_text()
    assert "<ul>" not in feed and "<li>" not in feed
    assert "https://a?x=1&amp;y=2" in feed          # bare source URL (XML-escaped)
    assert "https://b" in feed
    assert "T &amp; A &lt;tag&gt;" in feed          # title text survives
    assert "b1" in feed and "b2" in feed            # blurbs survive


def test_feed_description_carries_category_and_source_as_text(tmp_path):
    # Slack strips span/i markup, so the category must be plain [text]
    # and the source plain text after the blurb.
    _publish(tmp_path)
    feed = (tmp_path / "feed.xml").read_text()
    assert "[news] <a" in feed
    assert "[tool] <a" in feed
    assert "<i>(S&amp;P &lt;Wire&gt;)</i>" in feed
    assert "<i>(S2)</i>" in feed


def test_fallback_feed_description_has_bare_urls(tmp_path):
    articles = [{"link": "https://x/1", "title": "t1", "source": "S1"},
                {"link": None, "title": "skip"}]
    page = publish_fallback(
        articles, out_dir=tmp_path, base_url=BASE,
        iso_date="2026-06-09", edition="afternoon",
        edition_label="Afternoon", date_label="Tue Jun 9",
        generated_at=GEN_AT,
    ).read_text()
    feed = (tmp_path / "feed.xml").read_text()
    assert "<ul>" not in feed and "<li>" not in feed
    assert "https://x/1" in feed
    assert "skip" not in feed                        # linkless headline dropped
    assert "<i>(S1)</i>" in feed                     # source survives degraded mode
    assert '<span class="story-source">— S1</span>' in page


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


def test_publish_points_latest_at_newest_page(tmp_path):
    _publish(tmp_path)  # 2026-06-09 morning
    link = tmp_path / "latest.html"
    assert link.is_symlink()
    # relative target so it resolves inside the served dir
    import os
    assert os.readlink(link) == "2026-06-09-morning.html"
    assert link.resolve() == (tmp_path / "2026-06-09-morning.html").resolve()


def test_update_latest_follows_newest_and_swaps(tmp_path):
    for iso, edition in [("2026-06-09", "morning"), ("2026-06-10", "morning"),
                         ("2026-06-10", "afternoon")]:
        (tmp_path / f"{iso}-{edition}.json").write_text(
            json.dumps(_record(iso, edition))
        )
        (tmp_path / f"{iso}-{edition}.html").write_text("page")
    update_latest(tmp_path)
    import os
    # afternoon outranks morning within the newest day
    assert os.readlink(tmp_path / "latest.html") == "2026-06-10-afternoon.html"
    # re-running is idempotent and leaves no temp file behind
    update_latest(tmp_path)
    assert os.readlink(tmp_path / "latest.html") == "2026-06-10-afternoon.html"
    assert not (tmp_path / ".latest.html.tmp").exists()


def test_update_latest_noop_on_empty_dir(tmp_path):
    assert update_latest(tmp_path) is None
    assert not (tmp_path / "latest.html").exists()


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
