import os

import asyncpg
import pytest

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://postgres:REDACTED@192.168.0.89:5432/jina_clone_test",
)


@pytest.fixture
async def db():
    pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=2)
    async with pool.acquire() as conn:
        await conn.execute("TRUNCATE entries, news_summaries RESTART IDENTITY;")
    yield pool
    await pool.close()
