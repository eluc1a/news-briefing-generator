import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from jina_clone.briefing.config import (
    BriefingConfig, BriefsDef, SectionDef,
)
from jina_clone.briefing.generator import GeneratorFailure
from jina_clone.briefing.printer import PrintError
from jina_clone.briefing.schema import (
    Brief, Briefing, DataPoint, FrontMatter, LeadStory, OnThisDay, Panel,
    PanelItem, WeatherStrip,
)
from jina_clone.jobs.briefing import (
    BriefingResult, NotEnoughArticles, run_briefing,
)


CFG = BriefingConfig(
    sections=(
        SectionDef("national", "National",
                   ("us_national_news", "us_local_news", "policy"), 40),
        SectionDef("economy", "Economy & Markets",
                   ("business", "business_finance_news", "business_tech"), 40),
        SectionDef("ai", "AI & Technology", ("ai",), 40),
        SectionDef("international", "International",
                   ("international_news", "regional_international_news"), 40),
    ),
    briefs=BriefsDef(
        categories=("cybersecurity", "linux", "science", "startups", "tech",
                    "investigative_journalism"),
        limit=50,
    ),
    per_source_cap=5,
    front_matter_top_per_section=5,
    min_articles_total=4,
)

FIXTURE = Path("jina_clone/briefing/fixtures/sample_briefing.json")
EMERGENCY = Path("jina_clone/briefing/fixtures/emergency.json")
GOOD = Briefing.model_validate_json(FIXTURE.read_text())


def _row(link, category, source="s", content="ok"):
    return {"id": link, "title": "t", "link": link, "category": category,
            "source": source, "content": content, "published": None,
            "uploaded_at": None}


# ------------- happy path -------------

async def test_happy_path_fans_out_six_calls(tmp_path):
    fetched_args: list[dict] = []
    async def fetch(pool, *, categories, per_source_cap, limit, since_hours=24):
        fetched_args.append({"categories": list(categories), "limit": limit})
        # Five articles per section + briefs
        return [_row(f"https://{categories[0]}/{i}", categories[0]) for i in range(5)]

    fm_calls: list[dict] = []
    async def gen_fm(*, articles, weather, today, volume, **kw):
        fm_calls.append({"n_articles": len(articles)})
        return FrontMatter(
            lead=GOOD.lead,
            lead_source_url=articles[0]["link"],
            pull_quote=GOOD.pull_quote,
            data_point=GOOD.data_point,
            on_this_day=GOOD.on_this_day,
        )

    panel_calls: list[dict] = []
    async def gen_panel(*, section, articles, exclude_urls, **kw):
        panel_calls.append({
            "section": section.key,
            "n_articles": len(articles),
            "excluded": set(exclude_urls),
        })
        good_panel = next(p for p in GOOD.panels if p.section == section.title)
        return good_panel

    briefs_calls: list[dict] = []
    async def gen_briefs(*, articles, exclude_urls, **kw):
        briefs_calls.append({"n_articles": len(articles),
                             "excluded": set(exclude_urls)})
        return list(GOOD.briefs)

    rendered = []
    def render(briefing, out_path, *, generated_at, iso_date):
        rendered.append(briefing.lead.headline)
        out_path.write_bytes(b"%PDF-fake")
        return out_path

    printed = []
    def printer(pdf_path, *, queue):
        printed.append((pdf_path, queue))
        return "ok"

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
        config=CFG,
        briefings_dir=tmp_path,
        print_queue="brother",
        ntfy_topic="fox",
        weather_provider=lambda: WeatherStrip(
            temp_high=70, temp_low=50, conditions="x",
            sunrise="6:00", sunset="8:00", pollen="low",
        ).model_dump(),
        today_label="Sat",
        volume_label="Vol",
        generated_at_label="08:11 ET",
        iso_date="2026-04-19",
        fetch_articles=fetch,
        generate_front_matter=gen_fm,
        generate_panel=gen_panel,
        generate_briefs=gen_briefs,
        render=render,
        print_pdf=printer,
        notify_printed=notify_ok,
        notify_failure=notify_fail,
        insert_summary=insert_summary,
        emergency_path=EMERGENCY,
    )
    assert isinstance(result, BriefingResult)
    assert result.printed
    assert not result.emergency_used

    # Five fetch calls — one per section + briefs
    assert len(fetched_args) == 5
    fetched_cat_sets = {frozenset(a["categories"]) for a in fetched_args}
    assert frozenset(("us_national_news", "us_local_news", "policy")) in fetched_cat_sets
    assert frozenset(("cybersecurity", "linux", "science", "startups", "tech",
                      "investigative_journalism")) in fetched_cat_sets

    # Front matter called once, with at most 4 × front_matter_top_per_section articles
    assert len(fm_calls) == 1
    assert fm_calls[0]["n_articles"] <= 4 * CFG.front_matter_top_per_section

    # Four panel calls, one per section
    assert {c["section"] for c in panel_calls} == {"national", "economy", "ai", "international"}
    # Each panel received the front-matter lead URL in its exclude set
    for c in panel_calls:
        assert len(c["excluded"]) == 1

    # Briefs call received the same exclude set
    assert len(briefs_calls) == 1
    assert len(briefs_calls[0]["excluded"]) == 1

    # Print + DB write happened
    assert printed and printed[0][1] == "brother"
    assert notified_ok == [("fox", 2)]
    assert inserted and inserted[0][0] == "briefing"


# ------------- not enough articles -------------

async def test_aborts_when_zero_articles(tmp_path):
    async def fetch(pool, *, categories, per_source_cap, limit, since_hours=24):
        return []

    notified = []
    def notify_fail(*, topic, reason):
        notified.append(reason)

    async def noop(*a, **kw):
        raise AssertionError("generators should not run")

    with pytest.raises(NotEnoughArticles):
        await run_briefing(
            pool=MagicMock(),
            config=CFG,
            briefings_dir=tmp_path,
            print_queue="brother",
            ntfy_topic="t",
            weather_provider=lambda: {"temp_high": 70, "temp_low": 50,
                                      "conditions": "x", "sunrise": "6:00",
                                      "sunset": "8:00", "pollen": "low"},
            today_label="x", volume_label="y",
            generated_at_label="z", iso_date="2026-04-19",
            fetch_articles=fetch,
            generate_front_matter=noop,
            generate_panel=noop,
            generate_briefs=noop,
            render=lambda *a, **kw: None,
            print_pdf=lambda *a, **kw: None,
            notify_printed=lambda **kw: None,
            notify_failure=notify_fail,
            insert_summary=lambda *a, **kw: None,
            emergency_path=EMERGENCY,
        )
    assert notified


# ------------- emergency fallback -------------

async def test_any_generator_failure_triggers_emergency(tmp_path):
    async def fetch(pool, *, categories, per_source_cap, limit, since_hours=24):
        return [_row(f"https://{categories[0]}/{i}", categories[0]) for i in range(5)]

    async def gen_fm(*, articles, weather, today, volume, **kw):
        return FrontMatter(
            lead=GOOD.lead,
            lead_source_url=articles[0]["link"],
            pull_quote=GOOD.pull_quote,
            data_point=GOOD.data_point,
            on_this_day=GOOD.on_this_day,
        )

    # Economy call fails; others would succeed
    async def gen_panel(*, section, articles, exclude_urls, **kw):
        if section.key == "economy":
            raise GeneratorFailure("bad json twice")
        return next(p for p in GOOD.panels if p.section == section.title)

    async def gen_briefs(*, articles, exclude_urls, **kw):
        return list(GOOD.briefs)

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
        config=CFG,
        briefings_dir=tmp_path,
        print_queue="brother",
        ntfy_topic="t",
        weather_provider=lambda: {"temp_high": 70, "temp_low": 50,
                                  "conditions": "x", "sunrise": "6:00",
                                  "sunset": "8:00", "pollen": "low"},
        today_label="x", volume_label="y",
        generated_at_label="z", iso_date="2026-04-19",
        fetch_articles=fetch,
        generate_front_matter=gen_fm,
        generate_panel=gen_panel,
        generate_briefs=gen_briefs,
        render=render,
        print_pdf=lambda pdf, *, queue: "ok",
        notify_printed=lambda **kw: None,
        notify_failure=notify_fail,
        insert_summary=insert_summary,
        emergency_path=EMERGENCY,
    )
    assert result.printed
    assert result.emergency_used
    assert notified_fail
    # Emergency briefing was rendered
    assert any("failed" in h.lower() or "emergency" in h.lower() for h in rendered)
    assert inserted == []   # no DB write on emergency


async def test_front_matter_failure_also_triggers_emergency(tmp_path):
    async def fetch(pool, *, categories, per_source_cap, limit, since_hours=24):
        return [_row(f"https://{categories[0]}/{i}", categories[0]) for i in range(5)]

    async def gen_fm(*, articles, weather, today, volume, **kw):
        raise GeneratorFailure("fm failed twice")

    async def gen_panel(*, section, articles, exclude_urls, **kw):
        raise AssertionError("should not be called if front matter fails")

    async def gen_briefs(*, articles, exclude_urls, **kw):
        raise AssertionError("should not be called if front matter fails")

    rendered = []
    def render(briefing, out_path, *, generated_at, iso_date):
        rendered.append(briefing.lead.headline)
        out_path.write_bytes(b"%PDF-fake")
        return out_path

    notified_fail = []
    def notify_fail(*, topic, reason):
        notified_fail.append(reason)

    result = await run_briefing(
        pool=MagicMock(),
        config=CFG,
        briefings_dir=tmp_path,
        print_queue="brother",
        ntfy_topic="t",
        weather_provider=lambda: {"temp_high": 70, "temp_low": 50,
                                  "conditions": "x", "sunrise": "6:00",
                                  "sunset": "8:00", "pollen": "low"},
        today_label="x", volume_label="y",
        generated_at_label="z", iso_date="2026-04-19",
        fetch_articles=fetch,
        generate_front_matter=gen_fm,
        generate_panel=gen_panel,
        generate_briefs=gen_briefs,
        render=render,
        print_pdf=lambda pdf, *, queue: "ok",
        notify_printed=lambda **kw: None,
        notify_failure=notify_fail,
        insert_summary=lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("should not insert on emergency")
        ),
        emergency_path=EMERGENCY,
    )
    assert result.emergency_used
    assert notified_fail


# ------------- print failure still propagates -------------

async def test_print_failure_still_raises(tmp_path):
    async def fetch(pool, *, categories, per_source_cap, limit, since_hours=24):
        return [_row(f"https://{categories[0]}/{i}", categories[0]) for i in range(5)]

    async def gen_fm(*, articles, weather, today, volume, **kw):
        return FrontMatter(
            lead=GOOD.lead, lead_source_url=articles[0]["link"],
            pull_quote=GOOD.pull_quote,
            data_point=GOOD.data_point, on_this_day=GOOD.on_this_day,
        )

    async def gen_panel(*, section, articles, exclude_urls, **kw):
        return next(p for p in GOOD.panels if p.section == section.title)

    async def gen_briefs(*, articles, exclude_urls, **kw):
        return list(GOOD.briefs)

    def render(briefing, out_path, *, generated_at, iso_date):
        out_path.write_bytes(b"%PDF-fake")
        return out_path

    def printer(pdf_path, *, queue):
        raise PrintError("queue not found")

    notified_fail = []
    def notify_fail(*, topic, reason):
        notified_fail.append(reason)

    with pytest.raises(PrintError):
        await run_briefing(
            pool=MagicMock(),
            config=CFG,
            briefings_dir=tmp_path,
            print_queue="brother",
            ntfy_topic="t",
            weather_provider=lambda: {"temp_high": 70, "temp_low": 50,
                                      "conditions": "x", "sunrise": "6:00",
                                      "sunset": "8:00", "pollen": "low"},
            today_label="x", volume_label="y",
            generated_at_label="z", iso_date="2026-04-19",
            fetch_articles=fetch,
            generate_front_matter=gen_fm,
            generate_panel=gen_panel,
            generate_briefs=gen_briefs,
            render=render,
            print_pdf=printer,
            notify_printed=lambda **kw: None,
            notify_failure=notify_fail,
            insert_summary=lambda *a, **kw: None,
            emergency_path=EMERGENCY,
        )
    assert notified_fail and "queue not found" in notified_fail[0]
    pdfs = list(tmp_path.glob("*.pdf"))
    assert len(pdfs) == 1


# ------------- assemble_briefing (pure core) -------------

async def test_assemble_briefing_happy_path_returns_briefing_and_count():
    from jina_clone.jobs.briefing import assemble_briefing

    async def fetch(pool, *, categories, per_source_cap, limit, since_hours=24):
        # Return 5 rows per call; 4 sections + 1 briefs call = 25 total
        return [_row(f"https://{categories[0]}/{i}", categories[0]) for i in range(5)]

    async def gen_fm(*, articles, weather, today, volume, **kw):
        return FrontMatter(
            lead=GOOD.lead,
            lead_source_url=articles[0]["link"],
            pull_quote=GOOD.pull_quote,
            data_point=GOOD.data_point,
            on_this_day=GOOD.on_this_day,
        )

    async def gen_panel(*, section, articles, exclude_urls, **kw):
        return next(p for p in GOOD.panels if p.section == section.title)

    async def gen_briefs(*, articles, exclude_urls, **kw):
        return list(GOOD.briefs)

    briefing, count = await assemble_briefing(
        pool=MagicMock(),
        config=CFG,
        weather_provider=lambda: WeatherStrip(
            temp_high=70, temp_low=50, conditions="x",
            sunrise="6:00", sunset="8:00", pollen="low",
        ).model_dump(),
        today_label="Sat",
        volume_label="Vol",
        iso_date="2026-04-19",
        fetch_articles=fetch,
        generate_front_matter=gen_fm,
        generate_panel=gen_panel,
        generate_briefs=gen_briefs,
    )
    assert isinstance(briefing, Briefing)
    assert briefing.date == "2026-04-19"
    assert briefing.volume == "Vol"
    assert len(briefing.panels) == 4
    # 5 articles per section (4 sections) + 5 briefs = 25 total
    assert count == 25


async def test_assemble_briefing_raises_not_enough_articles():
    from jina_clone.jobs.briefing import assemble_briefing, NotEnoughArticles

    async def fetch(pool, *, categories, per_source_cap, limit, since_hours=24):
        return []  # Zero articles total

    async def noop(*a, **kw):
        raise AssertionError("generators should not run when articles are insufficient")

    with pytest.raises(NotEnoughArticles):
        await assemble_briefing(
            pool=MagicMock(),
            config=CFG,
            weather_provider=lambda: {"temp_high": 70, "temp_low": 50,
                                      "conditions": "x", "sunrise": "6:00",
                                      "sunset": "8:00", "pollen": "low"},
            today_label="x",
            volume_label="y",
            iso_date="2026-04-19",
            fetch_articles=fetch,
            generate_front_matter=noop,
            generate_panel=noop,
            generate_briefs=noop,
        )


async def test_assemble_briefing_bubbles_generator_failure():
    from jina_clone.jobs.briefing import assemble_briefing

    async def fetch(pool, *, categories, per_source_cap, limit, since_hours=24):
        return [_row(f"https://{categories[0]}/{i}", categories[0]) for i in range(5)]

    async def gen_fm(*, articles, weather, today, volume, **kw):
        raise GeneratorFailure("front matter failed twice")

    async def gen_panel(*, section, articles, exclude_urls, **kw):
        raise AssertionError("should not run if front matter fails")

    async def gen_briefs(*, articles, exclude_urls, **kw):
        raise AssertionError("should not run if front matter fails")

    with pytest.raises(GeneratorFailure):
        await assemble_briefing(
            pool=MagicMock(),
            config=CFG,
            weather_provider=lambda: {"temp_high": 70, "temp_low": 50,
                                      "conditions": "x", "sunrise": "6:00",
                                      "sunset": "8:00", "pollen": "low"},
            today_label="x",
            volume_label="y",
            iso_date="2026-04-19",
            fetch_articles=fetch,
            generate_front_matter=gen_fm,
            generate_panel=gen_panel,
            generate_briefs=gen_briefs,
        )
