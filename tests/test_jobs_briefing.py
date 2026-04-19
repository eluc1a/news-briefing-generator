import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from jina_clone.briefing.config import BriefingCategories, PanelDef
from jina_clone.briefing.generator import GeneratorFailure
from jina_clone.briefing.printer import PrintError
from jina_clone.briefing.schema import Briefing
from jina_clone.jobs.briefing import (
    BriefingResult,
    NotEnoughArticles,
    run_briefing,
)


CATS = BriefingCategories(
    panels=(
        PanelDef("ai", "AI & Technology", ("ai", "llm_tools")),
        PanelDef("national", "National", ("us_national_news",)),
        PanelDef("economy", "Economy & Markets", ("business",)),
        PanelDef("international", "International", ("international_news",)),
    ),
    briefs_categories=("tech", "science"),
    min_articles_total=4,
)

FIXTURE = Path("jina_clone/briefing/fixtures/sample_briefing.json")
EMERGENCY = Path("jina_clone/briefing/fixtures/emergency.json")
GOOD = Briefing.model_validate_json(FIXTURE.read_text())


def _row(link, category, content="ok"):
    return {"id": link, "title": "t", "link": link, "category": category,
            "source": "s", "content": content, "published": None, "uploaded_at": None}


async def test_happy_path_runs_full_pipeline(tmp_path):
    fetched_categories: list[list[str]] = []

    async def fetch(pool, *, categories, since_hours, limit):
        fetched_categories.append(list(categories))
        return [
            _row("https://a", "ai"),
            _row("https://b", "ai"),
            _row("https://c", "us_national_news"),
            _row("https://d", "business"),
            _row("https://e", "international_news"),
            _row("https://f", "tech"),
        ]

    generated_args = {}
    async def generate(**kwargs):
        generated_args.update(kwargs)
        return GOOD

    rendered = []
    def render(briefing, out_path, *, generated_at, iso_date):
        rendered.append(out_path)
        out_path.write_bytes(b"%PDF-fake")
        return out_path

    printed = []
    def printer(pdf_path, *, queue):
        printed.append((pdf_path, queue))
        return "request id is brother-1"

    notified_ok = []
    def notify_ok(*, topic, pages):
        notified_ok.append((topic, pages))
    def notify_fail(*, topic, reason):
        raise AssertionError("should not notify failure on happy path")

    inserted = []
    async def insert_summary(pool, *, category, headline, facts, article_count):
        inserted.append((category, headline, article_count))
        return 1

    result = await run_briefing(
        pool=MagicMock(),
        categories=CATS,
        briefings_dir=tmp_path,
        print_queue="brother",
        ntfy_topic="fox-briefings",
        weather_provider=lambda: {"temp_high": 70, "temp_low": 50, "conditions": "x", "sunrise": "6:00", "sunset": "8:00", "pollen": "low"},
        today_label="Saturday, April 18, 2026",
        volume_label="Vol. I · No. 108",
        generated_at_label="08:11 ET",
        iso_date="2026-04-18",
        fetch_articles=fetch,
        generate=generate,
        render=render,
        print_pdf=printer,
        notify_printed=notify_ok,
        notify_failure=notify_fail,
        insert_summary=insert_summary,
        emergency_path=EMERGENCY,
    )

    assert isinstance(result, BriefingResult)
    assert result.printed
    assert len(fetched_categories) == 1
    # Articles passed to generate are partitioned by panel
    by_panel = generated_args["articles_by_panel"]
    assert {"ai", "national", "economy", "international"} <= set(by_panel.keys())
    assert len(by_panel["ai"]) == 2
    # Briefs pool gets the leftover (tech)
    assert len(generated_args["briefs_pool"]) == 1
    # Print, notify, news_summaries write all happened
    assert len(rendered) == 1
    assert printed and printed[0][1] == "brother"
    assert notified_ok == [("fox-briefings", 2)]
    assert inserted and inserted[0][0] == "briefing"


async def test_aborts_when_too_few_articles():
    async def fetch(pool, *, categories, since_hours, limit):
        return [_row("https://a", "ai"), _row("https://b", "ai")]  # only 2, min is 4

    notified = []
    def notify_fail(*, topic, reason):
        notified.append(reason)

    with pytest.raises(NotEnoughArticles):
        await run_briefing(
            pool=MagicMock(),
            categories=CATS,
            briefings_dir=Path("/tmp"),
            print_queue="brother",
            ntfy_topic="t",
            weather_provider=lambda: {"temp_high": 70, "temp_low": 50, "conditions": "x", "sunrise": "6:00", "sunset": "8:00", "pollen": "low"},
            today_label="Saturday, April 18, 2026",
            volume_label="Vol. I · No. 108",
            generated_at_label="08:11 ET",
            iso_date="2026-04-18",
            fetch_articles=fetch,
            generate=lambda **kw: (_ for _ in ()).throw(AssertionError("should not generate")),
            render=lambda *a, **kw: None,
            print_pdf=lambda *a, **kw: None,
            notify_printed=lambda **kw: None,
            notify_failure=notify_fail,
            insert_summary=lambda *a, **kw: None,
            emergency_path=EMERGENCY,
        )
    assert notified and "too few" in notified[0].lower()


async def test_falls_back_to_emergency_on_generator_failure(tmp_path):
    async def fetch(pool, *, categories, since_hours, limit):
        return [_row(f"https://{i}", "ai") for i in range(5)]

    async def generate(**kwargs):
        raise GeneratorFailure("validation failed twice")

    rendered = []
    def render(briefing, out_path, *, generated_at, iso_date):
        rendered.append(briefing.lead.headline)
        out_path.write_bytes(b"%PDF-fake")
        return out_path

    notified_fail = []
    def notify_fail(*, topic, reason):
        notified_fail.append(reason)

    inserted = []
    async def insert_summary(pool, *, category, headline, facts, article_count):
        inserted.append(headline)
        return 1

    result = await run_briefing(
        pool=MagicMock(),
        categories=CATS,
        briefings_dir=tmp_path,
        print_queue="brother",
        ntfy_topic="t",
        weather_provider=lambda: {"temp_high": 70, "temp_low": 50, "conditions": "x", "sunrise": "6:00", "sunset": "8:00", "pollen": "low"},
        today_label="x",
        volume_label="y",
        generated_at_label="z",
        iso_date="2026-04-18",
        fetch_articles=fetch,
        generate=generate,
        render=render,
        print_pdf=lambda pdf, *, queue: "ok",
        notify_printed=lambda **kw: None,
        notify_failure=notify_fail,
        insert_summary=insert_summary,
        emergency_path=EMERGENCY,
    )
    assert result.printed
    assert result.emergency_used
    # Emergency briefing was rendered
    assert any("emergency" in h.lower() or "failed" in h.lower() for h in rendered)
    # Failure was announced
    assert notified_fail
    # No DB row written when emergency is used
    assert inserted == []


async def test_print_failure_keeps_pdf_and_notifies(tmp_path):
    async def fetch(pool, *, categories, since_hours, limit):
        return [_row(f"https://{i}", "ai") for i in range(5)]

    async def generate(**kwargs):
        return GOOD

    def render(briefing, out_path, *, generated_at, iso_date):
        out_path.write_bytes(b"%PDF-fake")
        return out_path

    def printer(pdf_path, *, queue):
        raise PrintError("queue not found")

    notified_fail = []
    def notify_fail(*, topic, reason):
        notified_fail.append(reason)

    inserted = []
    async def insert_summary(pool, *, category, headline, facts, article_count):
        inserted.append(headline)
        return 1

    with pytest.raises(PrintError):
        await run_briefing(
            pool=MagicMock(),
            categories=CATS,
            briefings_dir=tmp_path,
            print_queue="brother",
            ntfy_topic="t",
            weather_provider=lambda: {"temp_high": 70, "temp_low": 50, "conditions": "x", "sunrise": "6:00", "sunset": "8:00", "pollen": "low"},
            today_label="x",
            volume_label="y",
            generated_at_label="z",
            iso_date="2026-04-18",
            fetch_articles=fetch,
            generate=generate,
            render=render,
            print_pdf=printer,
            notify_printed=lambda **kw: None,
            notify_failure=notify_fail,
            insert_summary=insert_summary,
            emergency_path=EMERGENCY,
        )
    assert notified_fail and "queue not found" in notified_fail[0]
    assert inserted == []  # no DB write on print failure
    # PDF was preserved on disk for manual reprint
    pdfs = list(tmp_path.glob("*.pdf"))
    assert len(pdfs) == 1
