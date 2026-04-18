from datetime import datetime, timezone

from jina_clone.storage.db import (
    insert_entry,
    link_exists,
    fetch_unsummarized,
    mark_summarized,
    insert_summary,
)


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
    rows = await fetch_unsummarized(db, source_names=["Ours"])
    assert len(rows) == 1
    assert rows[0]["link"] == "https://x.example/ours"


async def test_fetch_unsummarized_excludes_null_content(db):
    await insert_entry(db, url="https://x.example/ok", title="ok", source="Ours",
                       category="ai", content="body", published=None)
    await insert_entry(db, url="https://x.example/err", title="err", source="Ours",
                       category="ai", content=None, published=None)
    rows = await fetch_unsummarized(db, source_names=["Ours"])
    assert [r["link"] for r in rows] == ["https://x.example/ok"]


async def test_mark_summarized_updates_rows(db):
    await insert_entry(db, url="https://x.example/a", title="a", source="Ours",
                       category="ai", content="body", published=None)
    await mark_summarized(db, links=["https://x.example/a"])
    rows = await fetch_unsummarized(db, source_names=["Ours"])
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
