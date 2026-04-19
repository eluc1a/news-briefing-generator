from datetime import datetime
from typing import Sequence

import asyncpg


async def create_pool(database_url: str) -> asyncpg.Pool:
    return await asyncpg.create_pool(database_url, min_size=1, max_size=4)


async def link_exists(pool: asyncpg.Pool, url: str) -> bool:
    async with pool.acquire() as conn:
        row = await conn.fetchval("SELECT 1 FROM entries WHERE link = $1 LIMIT 1", url)
    return row is not None


async def insert_entry(
    pool: asyncpg.Pool,
    *,
    url: str,
    title: str | None,
    source: str,
    category: str,
    content: str | None,
    published: datetime | None,
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO entries (id, title, link, published, source, category, content)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (id) DO NOTHING
            """,
            url,
            title or "(no title)",
            url,
            published,
            source,
            category,
            content,
        )


async def fetch_unsummarized(
    pool: asyncpg.Pool,
    *,
    source_names: Sequence[str],
    category: str,
    since: datetime,
) -> list[asyncpg.Record]:
    async with pool.acquire() as conn:
        return await conn.fetch(
            """
            SELECT id, title, link, source, category, content, published, uploaded_at
            FROM entries
            WHERE source = ANY($1::text[])
              AND category = $2
              AND summarized_at IS NULL
              AND content IS NOT NULL
              AND COALESCE(published, uploaded_at) >= $3
            ORDER BY uploaded_at ASC
            """,
            list(source_names),
            category,
            since,
        )


async def mark_summarized(pool: asyncpg.Pool, *, links: Sequence[str]) -> None:
    if not links:
        return
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE entries SET summarized_at = now() WHERE link = ANY($1::text[])",
            list(links),
        )


async def insert_summary(
    pool: asyncpg.Pool,
    *,
    category: str,
    headline: str,
    facts: str,
    article_count: int,
) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO news_summaries (category, headline, facts, article_count)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            category,
            headline,
            facts,
            article_count,
        )
