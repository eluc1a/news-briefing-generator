from datetime import datetime, timedelta, timezone

import pytest

from jina_clone.storage.db import (
    fetch_recent_articles_by_category,
    insert_entry,
)


async def _seed(db, *, link, source, category, content, published_offset_hours=0):
    await insert_entry(
        db,
        url=link,
        title=f"title for {link}",
        source=source,
        category=category,
        content=content,
        published=datetime.now(timezone.utc) - timedelta(hours=published_offset_hours),
    )


async def test_returns_only_requested_categories(db):
    await _seed(db, link="https://a", source="src", category="ai", content="c")
    await _seed(db, link="https://b", source="src", category="science", content="c")
    await _seed(db, link="https://c", source="src", category="us_national_news", content="c")
    rows = await fetch_recent_articles_by_category(
        db, categories=["ai", "us_national_news"]
    )
    links = {r["link"] for r in rows}
    assert links == {"https://a", "https://c"}


async def test_skips_null_content(db):
    await _seed(db, link="https://a", source="src", category="ai", content=None)
    await _seed(db, link="https://b", source="src", category="ai", content="ok")
    rows = await fetch_recent_articles_by_category(db, categories=["ai"])
    assert {r["link"] for r in rows} == {"https://b"}


async def test_respects_since_hours(db):
    # uploaded_at default is now() in the table; we test that a since_hours
    # window of 0 returns nothing because uploaded_at is "just now" but the
    # filter should be `>= now() - 0`.
    await _seed(db, link="https://old", source="src", category="ai", content="c")
    # All freshly-inserted rows have uploaded_at = now(); since_hours=24
    # should include them.
    rows = await fetch_recent_articles_by_category(
        db, categories=["ai"], since_hours=24
    )
    assert len(rows) == 1
    # since_hours=-1 (impossible window) should return zero rows
    none = await fetch_recent_articles_by_category(
        db, categories=["ai"], since_hours=-1
    )
    assert len(none) == 0


async def test_respects_limit(db):
    for i in range(5):
        await _seed(db, link=f"https://e{i}", source="src", category="ai", content="c")
    rows = await fetch_recent_articles_by_category(
        db, categories=["ai"], limit=3
    )
    assert len(rows) == 3


async def test_empty_categories_returns_empty(db):
    await _seed(db, link="https://a", source="src", category="ai", content="c")
    rows = await fetch_recent_articles_by_category(db, categories=[])
    assert rows == []
