from pathlib import Path

from jina_clone.jobs.summarize import run_summarize
from jina_clone.storage.db import insert_entry, fetch_unsummarized


class FakeProvider:
    name = "fake"
    model = "fake-1"

    def __init__(self, response):
        self.response = response
        self.calls = []

    async def summarize(self, system, user):
        self.calls.append((system, user))
        return self.response


async def test_run_summarize_no_articles_returns_none(db, tmp_path):
    provider = FakeProvider({"headline": "x", "body": "y"})
    result = await run_summarize(
        db,
        source_names=["Ours"],
        provider=provider,
        summaries_dir=tmp_path,
    )
    assert result is None
    assert provider.calls == []


async def test_run_summarize_writes_file_row_and_marks_entries(db, tmp_path):
    await insert_entry(db, url="https://x/1", title="A", source="Ours",
                       category="ai", content="aaa", published=None)
    await insert_entry(db, url="https://x/2", title="B", source="Ours",
                       category="ai", content="bbb", published=None)

    provider = FakeProvider({"headline": "Daily AI", "body": "## Theme\n- bullet"})
    result = await run_summarize(
        db,
        source_names=["Ours"],
        provider=provider,
        summaries_dir=tmp_path,
        category="ai",
    )

    assert result is not None
    path = Path(result["output_path"])
    assert path.exists()
    content = path.read_text()
    assert "Daily AI" in content
    assert "## Theme" in content
    assert "article_count: 2" in content

    # both entries now marked summarized
    assert await fetch_unsummarized(db, source_names=["Ours"]) == []

    # news_summaries row present
    async with db.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM news_summaries WHERE id=$1", result["summary_id"])
        assert row["headline"] == "Daily AI"
        assert row["article_count"] == 2


async def test_run_summarize_llm_failure_does_not_mark_entries(db, tmp_path):
    await insert_entry(db, url="https://x/1", title="A", source="Ours",
                       category="ai", content="aaa", published=None)

    class Boom:
        name = "boom"; model = "boom"
        async def summarize(self, system, user):
            raise RuntimeError("LLM exploded")

    import pytest
    with pytest.raises(RuntimeError):
        await run_summarize(
            db,
            source_names=["Ours"],
            provider=Boom(),
            summaries_dir=tmp_path,
        )

    rows = await fetch_unsummarized(db, source_names=["Ours"])
    assert len(rows) == 1
    assert list(tmp_path.iterdir()) == []
