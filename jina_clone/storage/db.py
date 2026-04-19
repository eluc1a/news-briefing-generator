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


async def fetch_section_articles(
    pool: asyncpg.Pool,
    *,
    categories: Sequence[str],
    per_source_cap: int = 5,
    limit: int = 40,
    since_hours: float = 24,
) -> list[asyncpg.Record]:
    """Articles for a single briefing section, capped per source.

    `per_source_cap` keeps one high-volume outlet from dominating the
    pool (e.g., stops The Hindu from owning the International panel).
    """
    if not categories:
        return []
    async with pool.acquire() as conn:
        return await conn.fetch(
            """
            WITH ranked AS (
              SELECT
                id, title, link, published, source, category, content, uploaded_at,
                ROW_NUMBER() OVER (
                  PARTITION BY source
                  ORDER BY published DESC NULLS LAST, uploaded_at DESC
                ) AS src_rank
              FROM entries
              WHERE category = ANY($1::text[])
                AND content IS NOT NULL
                AND uploaded_at >= now() - ($2 || ' hours')::interval
            )
            SELECT id, title, link, published, source, category, content, uploaded_at
            FROM ranked
            WHERE src_rank <= $3
            ORDER BY published DESC NULLS LAST, uploaded_at DESC
            LIMIT $4
            """,
            list(categories),
            str(since_hours),
            per_source_cap,
            limit,
        )


async def fetch_recent_articles_by_category(
    pool: asyncpg.Pool,
    *,
    categories: Sequence[str],
    since_hours: float = 24,
    limit: int = 80,
) -> list[asyncpg.Record]:
    """Articles uploaded in the last N hours, filtered to the given categories.

    Used by the briefing job. Read-only — does not touch summarized_at.
    Returns empty list if categories is empty (no SQL issued).
    """
    if not categories:
        return []
    async with pool.acquire() as conn:
        return await conn.fetch(
            """
            SELECT id, title, link, published, source, category, content, uploaded_at
            FROM entries
            WHERE category = ANY($1::text[])
              AND content IS NOT NULL
              AND uploaded_at >= now() - ($2 || ' hours')::interval
            ORDER BY published DESC NULLS LAST, uploaded_at DESC
            LIMIT $3
            """,
            list(categories),
            str(since_hours),
            limit,
        )
