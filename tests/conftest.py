import os

import asyncpg
import pytest_asyncio
from dotenv import load_dotenv

load_dotenv()

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://postgres@localhost:5432/jina_clone_test",
)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def db_pool():
    pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=2)
    yield pool
    await pool.close()


@pytest_asyncio.fixture(scope="function", loop_scope="session")
async def db(db_pool):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "TRUNCATE entries, news_summaries RESTART IDENTITY CASCADE;"
        )
    return db_pool
