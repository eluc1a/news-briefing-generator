from datetime import datetime, timedelta, timezone

from jina_clone.storage.db import (
    insert_entry,
    link_exists,
    fetch_unsummarized,
    mark_summarized,
    insert_summary,
    fetch_section_articles,
)


def _long_ago():
    return datetime(2000, 1, 1, tzinfo=timezone.utc)


async def test_insert_entry_and_link_exists(db):
    await insert_entry(
        db,
        url="https://x.example/a",
        title="Article A",
        source="Test Source",
        category="ai",
        content="body text",
        published=datetime(2026, 4, 18, 12, 0, tzinfo=timezone.utc),
    )
    assert await link_exists(db, "https://x.example/a") is True
    assert await link_exists(db, "https://x.example/missing") is False


async def test_insert_entry_with_null_content(db):
    await insert_entry(
        db,
        url="https://x.example/b",
        title="B",
        source="Test Source",
        category="ai",
        content=None,
        published=None,
    )
    assert await link_exists(db, "https://x.example/b") is True


async def test_fetch_unsummarized_only_returns_our_sources(db):
    await insert_entry(db, url="https://x.example/ours", title="ours", source="Ours",
                       category="ai", content="some text", published=None)
    await insert_entry(db, url="https://x.example/other", title="other", source="Other",
                       category="x", content="some text", published=None)
    rows = await fetch_unsummarized(db, source_names=["Ours"], category="ai", since=_long_ago())
    assert len(rows) == 1
    assert rows[0]["link"] == "https://x.example/ours"


async def test_fetch_unsummarized_excludes_null_content(db):
    await insert_entry(db, url="https://x.example/ok", title="ok", source="Ours",
                       category="ai", content="body", published=None)
    await insert_entry(db, url="https://x.example/err", title="err", source="Ours",
                       category="ai", content=None, published=None)
    rows = await fetch_unsummarized(db, source_names=["Ours"], category="ai", since=_long_ago())
    assert [r["link"] for r in rows] == ["https://x.example/ok"]


async def test_fetch_unsummarized_excludes_other_category(db):
    # Same source name, different category → must not return cross-pipeline rows.
    await insert_entry(db, url="https://x.example/our", title="our", source="Shared",
                       category="ai", content="body", published=None)
    await insert_entry(db, url="https://x.example/theirs", title="theirs", source="Shared",
                       category="llm_tools", content="body", published=None)
    rows = await fetch_unsummarized(db, source_names=["Shared"], category="ai", since=_long_ago())
    assert [r["link"] for r in rows] == ["https://x.example/our"]


async def test_fetch_unsummarized_excludes_outside_window(db):
    now = datetime.now(timezone.utc)
    await insert_entry(db, url="https://x.example/fresh", title="fresh", source="Ours",
                       category="ai", content="body", published=now - timedelta(hours=1))
    await insert_entry(db, url="https://x.example/stale", title="stale", source="Ours",
                       category="ai", content="body", published=now - timedelta(hours=48))
    rows = await fetch_unsummarized(
        db, source_names=["Ours"], category="ai", since=now - timedelta(hours=24),
    )
    assert [r["link"] for r in rows] == ["https://x.example/fresh"]


async def test_mark_summarized_updates_rows(db):
    await insert_entry(db, url="https://x.example/a", title="a", source="Ours",
                       category="ai", content="body", published=None)
    await mark_summarized(db, links=["https://x.example/a"])
    rows = await fetch_unsummarized(db, source_names=["Ours"], category="ai", since=_long_ago())
    assert rows == []


async def test_insert_summary_returns_id(db):
    summary_id = await insert_summary(
        db, category="ai", headline="H", facts="F", article_count=3
    )
    assert isinstance(summary_id, int)
    async with db.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM news_summaries WHERE id=$1", summary_id)
        assert row["headline"] == "H"
        assert row["article_count"] == 3


async def test_fetch_section_articles_filters_by_category(db):
    await insert_entry(db, url="https://x.example/1", title="a", source="S1",
                       category="us_national_news", content="body", published=None)
    await insert_entry(db, url="https://x.example/2", title="b", source="S1",
                       category="international_news", content="body", published=None)
    rows = await fetch_section_articles(
        db, categories=["us_national_news"], per_source_cap=5, limit=40,
    )
    assert [r["link"] for r in rows] == ["https://x.example/1"]


async def test_fetch_section_articles_per_source_cap(db):
    # Seven articles from one source; cap=5 should drop the two oldest.
    now = datetime.now(timezone.utc)
    for i in range(7):
        await insert_entry(
            db,
            url=f"https://s1.example/{i}",
            title=f"t{i}",
            source="S1",
            category="us_national_news",
            content="body",
            published=now - timedelta(hours=i),   # newest first (i=0)
        )
    rows = await fetch_section_articles(
        db, categories=["us_national_news"], per_source_cap=5, limit=40,
    )
    assert len(rows) == 5
    # The five newest (i=0..4) should survive.
    kept = {r["link"] for r in rows}
    assert kept == {f"https://s1.example/{i}" for i in range(5)}


async def test_fetch_section_articles_respects_limit(db):
    # 10 articles across 2 sources, cap=5 each; limit=6 should clip to 6.
    now = datetime.now(timezone.utc)
    for src in ("S1", "S2"):
        for i in range(5):
            await insert_entry(
                db,
                url=f"https://{src.lower()}.example/{i}",
                title=f"{src}-{i}",
                source=src,
                category="us_national_news",
                content="body",
                published=now - timedelta(hours=i),
            )
    rows = await fetch_section_articles(
        db, categories=["us_national_news"], per_source_cap=5, limit=6,
    )
    assert len(rows) == 6


async def test_fetch_section_articles_excludes_null_content(db):
    await insert_entry(db, url="https://x.example/ok", title="ok", source="S1",
                       category="us_national_news", content="body", published=None)
    await insert_entry(db, url="https://x.example/err", title="err", source="S1",
                       category="us_national_news", content=None, published=None)
    rows = await fetch_section_articles(
        db, categories=["us_national_news"], per_source_cap=5, limit=40,
    )
    assert [r["link"] for r in rows] == ["https://x.example/ok"]


async def test_fetch_section_articles_empty_categories_returns_empty(db):
    await insert_entry(db, url="https://x.example/1", title="a", source="S1",
                       category="us_national_news", content="body", published=None)
    rows = await fetch_section_articles(db, categories=[], per_source_cap=5, limit=40)
    assert rows == []


async def test_fetch_section_articles_respects_24h_window(db):
    now = datetime.now(timezone.utc)
    await insert_entry(db, url="https://x.example/fresh", title="fresh", source="S1",
                       category="us_national_news", content="body",
                       published=now - timedelta(hours=1))
    # "stale" inserted with past published; uploaded_at defaults to now() though,
    # so this row WILL appear (since_hours filter is on uploaded_at). To actually
    # simulate a stale row, insert and then rewrite uploaded_at via direct SQL.
    await insert_entry(db, url="https://x.example/stale", title="stale", source="S1",
                       category="us_national_news", content="body",
                       published=now - timedelta(hours=48))
    async with db.acquire() as conn:
        await conn.execute(
            "UPDATE entries SET uploaded_at = now() - interval '48 hours' "
            "WHERE link = $1",
            "https://x.example/stale",
        )
    rows = await fetch_section_articles(
        db, categories=["us_national_news"], per_source_cap=5, limit=40,
        since_hours=24,
    )
    assert [r["link"] for r in rows] == ["https://x.example/fresh"]
