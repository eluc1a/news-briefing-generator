"""Tests for the `briefing run --edition=...` CLI wiring.

Exercises the argparse + dispatch layer. The underlying jobs pipeline
is covered in test_jobs_briefing.py. Here we only verify that the CLI
derives the right title, pdf_path, volume_label, and window_hours
from the --edition flag and passes them to run_briefing.
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jina_clone import cli


def _dummy_settings(tmp_path: Path):
    s = MagicMock()
    s.database_url = "postgresql://fake"
    s.briefing_categories_file = Path("config/briefing_categories.yaml")
    s.briefings_dir = tmp_path
    s.print_queue = "brother"
    s.ntfy_topic = None
    return s


async def _capture_run_briefing_kwargs(edition: str, tmp_path: Path):
    """Invoke _briefing_run and return the kwargs it passed to run_briefing."""
    captured: dict = {}

    async def fake_run_briefing(**kw):
        captured.update(kw)
        from jina_clone.jobs.briefing import BriefingResult
        return BriefingResult(
            printed=True, emergency_used=False,
            pdf_path=kw["pdf_path"], article_count=0,
        )

    pool = MagicMock()
    pool.close = AsyncMock()

    with patch("jina_clone.cli.run_briefing", fake_run_briefing), \
         patch("jina_clone.cli.create_pool", AsyncMock(return_value=pool)):
        await cli._briefing_run(_dummy_settings(tmp_path), edition=edition)

    return captured


async def test_morning_edition_derives_morning_kwargs(tmp_path):
    kw = await _capture_run_briefing_kwargs("morning", tmp_path)
    assert kw["title"] == "The Morning Fox"
    assert kw["window_hours"] == 12
    assert kw["pdf_path"].name.endswith("-morning.pdf")
    assert "Morning" in kw["volume_label"]


async def test_evening_edition_derives_evening_kwargs(tmp_path):
    kw = await _capture_run_briefing_kwargs("evening", tmp_path)
    assert kw["title"] == "The Evening Fox"
    assert kw["window_hours"] == 12
    assert kw["pdf_path"].name.endswith("-evening.pdf")
    assert "Evening" in kw["volume_label"]


def test_briefing_run_requires_edition_flag(monkeypatch):
    """argparse must reject `briefing run` without --edition."""
    monkeypatch.setattr(sys, "argv", ["jina_clone", "briefing", "run"])
    with pytest.raises(SystemExit):
        cli.main()


def test_briefing_run_rejects_unknown_edition(monkeypatch):
    monkeypatch.setattr(
        sys, "argv",
        ["jina_clone", "briefing", "run", "--edition=afternoon"],
    )
    with pytest.raises(SystemExit):
        cli.main()
