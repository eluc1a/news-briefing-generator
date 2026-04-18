async def test_db_fixture_connects(db):
    async with db.acquire() as conn:
        row = await conn.fetchval("SELECT 1;")
        assert row == 1
