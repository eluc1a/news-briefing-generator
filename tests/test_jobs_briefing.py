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
    Brief, Briefing, DataPoint, EditorDecision, FrontMatter, LeadStory,
    OnThisDay, Panel, PanelItem, Source, WeatherStrip,
)
from jina_clone.jobs.briefing import (
    BriefingResult, NotEnoughArticles, _apply_cuts, _trim_positional,
    run_briefing,
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


def _async_weather(payload):
    """Wrap a dict/WeatherStrip payload as an async callable.
    Automatically adds hourly data if payload is a WeatherStrip."""
    if hasattr(payload, 'model_dump'):
        payload = payload.model_dump()
        # Add hourly data from the sample briefing
        payload["hourly"] = GOOD.hourly.model_dump()
    elif "hourly" not in payload:
        # Add hourly data from the sample briefing if not present
        payload["hourly"] = GOOD.hourly.model_dump()
    async def _fn():
        return payload
    return _fn


def _async_markets(items: list[dict] | None = None):
    payload = {"items": items or [
        {"symbol": s, "value": "—", "change": None}
        for s in ["SPY", "QQQ", "TQQQ", "BTC", "10Y", "CPI"]
    ]}
    async def _fn():
        return payload
    return _fn


def _row(link, category, source="s", content="ok"):
    return {"id": link, "title": "t", "link": link, "category": category,
            "source": source, "content": content, "published": None,
            "uploaded_at": None}


# ------------- happy path -------------

async def test_happy_path_fans_out_six_calls(tmp_path):
    fetched_args: list[dict] = []
    async def fetch(pool, *, categories, per_source_cap, limit, since_hours=24, source_caps=None):
        fetched_args.append({
            "categories": list(categories),
            "limit": limit,
            "since_hours": since_hours,
        })
        # Five articles per section + briefs
        return [_row(f"https://{categories[0]}/{i}", categories[0]) for i in range(5)]

    fm_calls: list[dict] = []
    async def gen_fm(*, articles, weather, today, volume, title, **kw):
        fm_calls.append({"n_articles": len(articles), "title": title})
        return FrontMatter(
            lead=GOOD.lead,
            lead_source_url=articles[0]["link"],
            pull_quote=GOOD.pull_quote,
            data_point=GOOD.data_point,
            on_this_day=GOOD.on_this_day,
        )

    panel_calls: list[dict] = []
    async def gen_panel(*, section, articles, exclude_urls, title, **kw):
        panel_calls.append({
            "section": section.key,
            "n_articles": len(articles),
            "excluded": set(exclude_urls),
            "title": title,
        })
        good_panel = next(p for p in GOOD.panels if p.section == section.title)
        return good_panel

    briefs_calls: list[dict] = []
    async def gen_briefs(*, articles, exclude_urls, title, **kw):
        briefs_calls.append({"n_articles": len(articles),
                             "excluded": set(exclude_urls),
                             "title": title})
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
    def notify_ok(*, topic, pages, **_kw):
        notified_ok.append((topic, pages))
    def notify_fail(*, topic, reason, **_kw):
        raise AssertionError("should not notify failure on happy path")

    inserted = []
    async def insert_summary(pool, *, category, headline, facts, article_count):
        inserted.append((category, headline, article_count))
        return 1

    result = await run_briefing(
        pool=MagicMock(),
        config=CFG,
        window_hours=12,
        title="The Morning Fox",
        pdf_path=tmp_path / "2026-04-19-morning.pdf",
        print_queue="brother",
        ntfy_topic="fox",
        weather_provider=_async_weather(WeatherStrip(
            temp_high=70, temp_low=50, conditions="x",
            sunrise="6:00", sunset="8:00", daylight="13h 24m",
        ).model_dump()),
        markets_provider=_async_markets(),
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

    # Window passed through to every fetch
    assert all(a["since_hours"] == 12 for a in fetched_args)

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

    # Every generator received the morning title
    assert all(c["title"] == "The Morning Fox" for c in fm_calls)
    assert all(c["title"] == "The Morning Fox" for c in panel_calls)
    assert all(c["title"] == "The Morning Fox" for c in briefs_calls)

    # Print + DB write happened
    assert printed and printed[0][1] == "brother"
    assert notified_ok == [("fox", 2)]
    assert inserted and inserted[0][0] == "briefing"


# ------------- evening edition -------------

async def test_run_briefing_evening_edition_threads_title_and_window(tmp_path):
    """--edition=evening flips title and filename; 12h window flows to DB."""
    fetched_args: list[dict] = []
    async def fetch(pool, *, categories, per_source_cap, limit, since_hours=24, source_caps=None):
        fetched_args.append({"since_hours": since_hours})
        return [_row(f"https://{categories[0]}/{i}", categories[0]) for i in range(5)]

    captured_titles: list[str] = []
    async def gen_fm(*, articles, weather, today, volume, title, **kw):
        captured_titles.append(title)
        return FrontMatter(
            lead=GOOD.lead, lead_source_url=articles[0]["link"],
            pull_quote=GOOD.pull_quote,
            data_point=GOOD.data_point, on_this_day=GOOD.on_this_day,
        )

    async def gen_panel(*, section, articles, exclude_urls, title, **kw):
        captured_titles.append(title)
        return next(p for p in GOOD.panels if p.section == section.title)

    async def gen_briefs(*, articles, exclude_urls, title, **kw):
        captured_titles.append(title)
        return list(GOOD.briefs)

    rendered: list = []
    def render(briefing, out_path, *, generated_at, iso_date):
        rendered.append(briefing)
        out_path.write_bytes(b"%PDF-fake")
        return out_path

    notified_ok: list = []
    def notify_ok(*, topic, title, pages):
        notified_ok.append({"title": title, "pages": pages})

    async def insert_summary(pool, **kw):
        return 42

    pdf_path = tmp_path / "2026-04-19-evening.pdf"
    result = await run_briefing(
        pool=MagicMock(),
        config=CFG,
        window_hours=12,
        title="The Evening Fox",
        pdf_path=pdf_path,
        print_queue="brother",
        ntfy_topic="fox",
        weather_provider=_async_weather({"temp_high": 60, "temp_low": 48,
                                  "conditions": "clear", "sunrise": "6:24",
                                  "sunset": "7:48", "daylight": "13h 24m"}),
        markets_provider=_async_markets(),
        today_label="Sun",
        volume_label="Vol. I · No. 109 · Evening",
        generated_at_label="20:11 ET",
        iso_date="2026-04-19",
        fetch_articles=fetch,
        generate_front_matter=gen_fm,
        generate_panel=gen_panel,
        generate_briefs=gen_briefs,
        render=render,
        print_pdf=lambda pdf, *, queue: "ok",
        notify_printed=notify_ok,
        notify_failure=lambda **kw: None,
        insert_summary=insert_summary,
        emergency_path=EMERGENCY,
    )

    assert result.printed
    assert result.pdf_path == pdf_path
    # All fetches used the 12-hour window
    assert all(a["since_hours"] == 12 for a in fetched_args)
    # All 6 generator calls (1 fm + 4 panels + 1 briefs) carried Evening Fox
    assert captured_titles == ["The Evening Fox"] * 6
    # Rendered briefing carries Evening Fox title
    assert rendered[0].title == "The Evening Fox"
    # ntfy push used the evening title
    assert notified_ok == [{"title": "The Evening Fox", "pages": 2}]


async def test_run_briefing_emergency_overwrites_title_from_param(tmp_path):
    """When emergency fires, the fixture's title is replaced by the edition title."""
    async def fetch(pool, *, categories, per_source_cap, limit, since_hours=24, source_caps=None):
        return [_row(f"https://{categories[0]}/{i}", categories[0]) for i in range(5)]

    async def gen_fm(*, articles, weather, today, volume, title, **kw):
        raise GeneratorFailure("boom")

    async def noop(**kw):
        raise AssertionError("should not run")

    rendered: list = []
    def render(briefing, out_path, *, generated_at, iso_date):
        rendered.append(briefing.title)
        out_path.write_bytes(b"%PDF-fake")
        return out_path

    result = await run_briefing(
        pool=MagicMock(),
        config=CFG,
        window_hours=12,
        title="The Evening Fox",
        pdf_path=tmp_path / "emergency.pdf",
        print_queue="brother",
        ntfy_topic=None,
        weather_provider=_async_weather({"temp_high": 0, "temp_low": 0,
                                  "conditions": "x", "sunrise": "-",
                                  "sunset": "-", "daylight": "13h 24m"}),
        markets_provider=_async_markets(),
        today_label="x", volume_label="y",
        generated_at_label="z", iso_date="2026-04-19",
        fetch_articles=fetch,
        generate_front_matter=gen_fm,
        generate_panel=noop,
        generate_briefs=noop,
        render=render,
        print_pdf=lambda pdf, *, queue: "ok",
        notify_printed=lambda **kw: None,
        notify_failure=lambda **kw: None,
        insert_summary=lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("no insert on emergency")
        ),
        emergency_path=EMERGENCY,
    )
    assert result.emergency_used
    assert rendered == ["The Evening Fox"]


# ------------- not enough articles -------------

async def test_aborts_when_zero_articles(tmp_path):
    async def fetch(pool, *, categories, per_source_cap, limit, since_hours=24, source_caps=None):
        return []

    notified = []
    def notify_fail(*, topic, reason, **_kw):
        notified.append(reason)

    async def noop(*a, **kw):
        raise AssertionError("generators should not run")

    with pytest.raises(NotEnoughArticles):
        await run_briefing(
            pool=MagicMock(),
            config=CFG,
            window_hours=12,
            title="The Morning Fox",
            pdf_path=tmp_path / "briefing.pdf",
            print_queue="brother",
            ntfy_topic="t",
            weather_provider=_async_weather({"temp_high": 70, "temp_low": 50,
                                      "conditions": "x", "sunrise": "6:00",
                                      "sunset": "8:00", "daylight": "13h 24m"}),
            markets_provider=_async_markets(),
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
    async def fetch(pool, *, categories, per_source_cap, limit, since_hours=24, source_caps=None):
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
    def notify_fail(*, topic, reason, **_kw):
        notified_fail.append(reason)

    inserted = []
    async def insert_summary(pool, *, category, headline, facts, article_count):
        inserted.append(headline)
        return 1

    result = await run_briefing(
        pool=MagicMock(),
        config=CFG,
        window_hours=12,
        title="The Morning Fox",
        pdf_path=tmp_path / "briefing.pdf",
        print_queue="brother",
        ntfy_topic="t",
        weather_provider=_async_weather({"temp_high": 70, "temp_low": 50,
                                  "conditions": "x", "sunrise": "6:00",
                                  "sunset": "8:00", "daylight": "13h 24m"}),
        markets_provider=_async_markets(),
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
    async def fetch(pool, *, categories, per_source_cap, limit, since_hours=24, source_caps=None):
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
    def notify_fail(*, topic, reason, **_kw):
        notified_fail.append(reason)

    result = await run_briefing(
        pool=MagicMock(),
        config=CFG,
        window_hours=12,
        title="The Morning Fox",
        pdf_path=tmp_path / "briefing.pdf",
        print_queue="brother",
        ntfy_topic="t",
        weather_provider=_async_weather({"temp_high": 70, "temp_low": 50,
                                  "conditions": "x", "sunrise": "6:00",
                                  "sunset": "8:00", "daylight": "13h 24m"}),
        markets_provider=_async_markets(),
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
    async def fetch(pool, *, categories, per_source_cap, limit, since_hours=24, source_caps=None):
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
    def notify_fail(*, topic, reason, **_kw):
        notified_fail.append(reason)

    with pytest.raises(PrintError):
        await run_briefing(
            pool=MagicMock(),
            config=CFG,
            window_hours=12,
            title="The Morning Fox",
            pdf_path=tmp_path / "briefing.pdf",
            print_queue="brother",
            ntfy_topic="t",
            weather_provider=_async_weather({"temp_high": 70, "temp_low": 50,
                                      "conditions": "x", "sunrise": "6:00",
                                      "sunset": "8:00", "daylight": "13h 24m"}),
            markets_provider=_async_markets(),
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


# ------------- print_enabled=False pauses the physical copy -------------

async def test_print_enabled_false_renders_but_skips_printer(tmp_path):
    """With print_enabled=False the PDF is still rendered, the run succeeds,
    and the briefing is logged — but the printer is never called."""
    async def fetch(pool, *, categories, per_source_cap, limit, since_hours=24, source_caps=None):
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

    printed = []
    def printer(pdf_path, *, queue):
        printed.append((pdf_path, queue))
        return "ok"

    inserted = []
    async def insert_summary(pool, **kw):
        inserted.append(kw)
        return 7

    pdf_path = tmp_path / "2026-04-19-morning.pdf"
    result = await run_briefing(
        pool=MagicMock(),
        config=CFG,
        window_hours=12,
        title="The Morning Fox",
        pdf_path=pdf_path,
        print_queue="brother",
        ntfy_topic="fox",
        weather_provider=_async_weather({"temp_high": 70, "temp_low": 50,
                                  "conditions": "x", "sunrise": "6:00",
                                  "sunset": "8:00", "daylight": "13h 24m"}),
        markets_provider=_async_markets(),
        today_label="Sat", volume_label="Vol",
        generated_at_label="08:11 ET", iso_date="2026-04-19",
        fetch_articles=fetch,
        generate_front_matter=gen_fm,
        generate_panel=gen_panel,
        generate_briefs=gen_briefs,
        render=render,
        print_pdf=printer,
        notify_printed=lambda **kw: None,
        notify_failure=lambda **kw: None,
        insert_summary=insert_summary,
        emergency_path=EMERGENCY,
        print_enabled=False,
    )

    assert result.printed  # run completed
    assert pdf_path.exists()  # still rendered for online publish
    assert printed == []  # printer NOT invoked
    assert inserted  # still logged to news_summaries


# ------------- assemble_briefing (pure core) -------------

async def test_assemble_briefing_happy_path_returns_briefing_and_count():
    from jina_clone.jobs.briefing import assemble_briefing

    async def fetch(pool, *, categories, per_source_cap, limit, since_hours=24, source_caps=None):
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
        window_hours=12,
        title="The Morning Fox",
        weather_provider=_async_weather(WeatherStrip(
            temp_high=70, temp_low=50, conditions="x",
            sunrise="6:00", sunset="8:00", daylight="13h 24m",
        ).model_dump()),
        markets_provider=_async_markets(),
        today_label="Sat",
        volume_label="Vol",
        iso_date="2026-04-19",
        fetch_articles=fetch,
        generate_front_matter=gen_fm,
        generate_panel=gen_panel,
        generate_briefs=gen_briefs,
    )
    assert isinstance(briefing, Briefing)
    assert briefing.date == "Sat"
    assert briefing.volume == "Vol"
    assert len(briefing.panels) == 4
    # 5 articles per section (4 sections) + 5 briefs = 25 total
    assert count == 25


async def test_assemble_briefing_raises_not_enough_articles():
    from jina_clone.jobs.briefing import assemble_briefing, NotEnoughArticles

    async def fetch(pool, *, categories, per_source_cap, limit, since_hours=24, source_caps=None):
        return []  # Zero articles total

    async def noop(*a, **kw):
        raise AssertionError("generators should not run when articles are insufficient")

    with pytest.raises(NotEnoughArticles):
        await assemble_briefing(
            pool=MagicMock(),
            config=CFG,
            window_hours=12,
            title="The Morning Fox",
            weather_provider=_async_weather({"temp_high": 70, "temp_low": 50,
                                      "conditions": "x", "sunrise": "6:00",
                                      "sunset": "8:00", "daylight": "13h 24m"}),
            markets_provider=_async_markets(),
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

    async def fetch(pool, *, categories, per_source_cap, limit, since_hours=24, source_caps=None):
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
            window_hours=12,
            title="The Morning Fox",
            weather_provider=_async_weather({"temp_high": 70, "temp_low": 50,
                                      "conditions": "x", "sunrise": "6:00",
                                      "sunset": "8:00", "daylight": "13h 24m"}),
            markets_provider=_async_markets(),
            today_label="x",
            volume_label="y",
            iso_date="2026-04-19",
            fetch_articles=fetch,
            generate_front_matter=gen_fm,
            generate_panel=gen_panel,
            generate_briefs=gen_briefs,
        )


# ------------- editor-in-chief dedup -------------

def _panel6(section_title="National"):
    return Panel(
        section=section_title,
        lede_headline=f"{section_title} lede",
        lede_body="body " * 10,
        lede_sources=[Source(url=f"https://{section_title}-lede", source="s")],
        also=[PanelItem(headline=f"{section_title} H{i}", body=f"B{i}",
                        sources=[]) for i in range(6)],
    )


def _briefs8():
    return [Brief(topic=f"T{i}", body=f"body {i}", sources=[]) for i in range(8)]


async def _assemble_with_fakes(
    *,
    gen_panel_result=None,
    gen_briefs_result=None,
    gen_panel=None,
    gen_briefs=None,
    generate_editor=None,
):
    """Standard fetch/front-matter/weather/markets fakes wired to
    assemble_briefing. Callers supply panel/briefs generation — either a
    `*_result` factory used by a default kwarg-recording fake, or a fully
    custom fake — plus an optional editor fake. Front matter's lead
    headline is fixed to "LEAD HEADLINE" so tests can assert on it."""
    from jina_clone.jobs.briefing import assemble_briefing

    async def fetch(pool, *, categories, per_source_cap, limit, since_hours=24, source_caps=None):
        return [_row(f"https://{categories[0]}/{i}", categories[0]) for i in range(5)]

    async def gen_fm(*, articles, weather, today, volume, title, **kw):
        return FrontMatter(
            lead=GOOD.lead.model_copy(update={"headline": "LEAD HEADLINE"}),
            lead_source_url=articles[0]["link"],
            pull_quote=GOOD.pull_quote,
            data_point=GOOD.data_point,
            on_this_day=GOOD.on_this_day,
        )

    if gen_panel is None:
        async def gen_panel(*, section, articles, exclude_urls, title, **kw):
            return gen_panel_result(section.title)

    if gen_briefs is None:
        async def gen_briefs(*, articles, exclude_urls, title, **kw):
            return gen_briefs_result()

    return await assemble_briefing(
        pool=MagicMock(),
        config=CFG,
        window_hours=12,
        title="The Morning Fox",
        weather_provider=_async_weather(WeatherStrip(
            temp_high=70, temp_low=50, conditions="x",
            sunrise="6:00", sunset="8:00", daylight="13h 24m",
        ).model_dump()),
        markets_provider=_async_markets(),
        today_label="Sat",
        volume_label="Vol",
        iso_date="2026-04-19",
        fetch_articles=fetch,
        generate_front_matter=gen_fm,
        generate_panel=gen_panel,
        generate_briefs=gen_briefs,
        generate_editor=generate_editor,
    )


async def test_editor_cuts_applied(tmp_path):
    """Editor decision removes the named indices; final counts exact."""
    editor_calls = []

    async def gen_editor(*, lead_headline, panels, briefs, title, **kw):
        editor_calls.append((lead_headline, [k for k, _ in panels], len(briefs)))
        cuts = [{"section": k, "index": i} for k, _ in panels for i in (0, 5)]
        cuts += [{"section": "briefs", "index": 6}, {"section": "briefs", "index": 7}]
        return EditorDecision.model_validate({"cuts": cuts, "lede_dupes": []})

    briefing, _ = await _assemble_with_fakes(
        gen_panel_result=_panel6, gen_briefs_result=_briefs8,
        generate_editor=gen_editor,
    )
    for panel in briefing.panels:
        assert len(panel.also) == 4
        # indices 0 and 5 were cut: H0 and H5 gone, H1..H4 remain
        assert [it.headline.split()[-1] for it in panel.also] == ["H1", "H2", "H3", "H4"]
    assert len(briefing.briefs) == 6
    assert [b.topic for b in briefing.briefs] == [f"T{i}" for i in range(6)]
    assert editor_calls  # editor was invoked with lead headline + keys


async def test_editor_failure_falls_back_to_positional_trim(tmp_path):
    async def gen_editor(**kw):
        raise GeneratorFailure("editor exploded")

    briefing, _ = await _assemble_with_fakes(
        gen_panel_result=_panel6, gen_briefs_result=_briefs8,
        generate_editor=gen_editor,
    )
    for panel in briefing.panels:
        assert len(panel.also) == 4
        assert panel.also[0].headline.endswith("H0")  # first 4 kept
    assert len(briefing.briefs) == 6


async def test_no_editor_positional_trim(tmp_path):
    briefing, _ = await _assemble_with_fakes(
        gen_panel_result=_panel6, gen_briefs_result=_briefs8,
        generate_editor=None,
    )
    for panel in briefing.panels:
        assert len(panel.also) == 4
    assert len(briefing.briefs) == 6


async def test_lead_headline_threaded_to_panels_and_briefs(tmp_path):
    seen = {"panel_avoid": [], "briefs_avoid": None}

    async def gen_panel(*, section, articles, exclude_urls, title, **kw):
        seen["panel_avoid"].append(kw.get("avoid_headlines"))
        return _panel6(section.title)

    async def gen_briefs(*, articles, exclude_urls, title, **kw):
        seen["briefs_avoid"] = kw.get("avoid_headlines")
        return _briefs8()

    await _assemble_with_fakes(gen_panel=gen_panel, gen_briefs=gen_briefs)
    assert all(a == ["LEAD HEADLINE"] for a in seen["panel_avoid"])
    assert seen["briefs_avoid"] == ["LEAD HEADLINE"]


async def test_lede_dupe_triggers_single_rerun(tmp_path):
    panel_calls = []

    async def gen_panel(*, section, articles, exclude_urls, title, **kw):
        panel_calls.append((section.key, set(exclude_urls),
                            kw.get("avoid_headlines")))
        return _panel6(section.title)

    async def gen_editor(*, lead_headline, panels, briefs, title, **kw):
        cuts = [{"section": k, "index": i} for k, _ in panels for i in (0, 5)]
        cuts += [{"section": "briefs", "index": 6}, {"section": "briefs", "index": 7}]
        return EditorDecision.model_validate({
            "cuts": cuts,
            "lede_dupes": [{"section": "national",
                            "duplicate_of": "front lead"}],
        })

    briefing, _ = await _assemble_with_fakes(
        gen_panel=gen_panel, gen_briefs_result=_briefs8,
        generate_editor=gen_editor,
    )
    national_calls = [c for c in panel_calls if c[0] == "national"]
    assert len(national_calls) == 2                       # initial + one rerun
    rerun = national_calls[1]
    assert "https://National-lede" in rerun[1]            # old lede URL excluded
    assert "National lede" in rerun[2]                    # old lede headline avoided
    # rerun panel trimmed positionally to 4
    nat = [p for p in briefing.panels if p.section == "National"][0]
    assert len(nat.also) == 4


async def test_lede_rerun_failure_keeps_original_panel(tmp_path):
    calls = {"national": 0}

    async def gen_panel(*, section, articles, exclude_urls, title, **kw):
        if section.key == "national":
            calls["national"] += 1
            if calls["national"] > 1:
                raise GeneratorFailure("rerun failed")
        return _panel6(section.title)

    async def gen_editor(*, lead_headline, panels, briefs, title, **kw):
        cuts = [{"section": k, "index": i} for k, _ in panels for i in (0, 5)]
        cuts += [{"section": "briefs", "index": 6}, {"section": "briefs", "index": 7}]
        return EditorDecision.model_validate({
            "cuts": cuts,
            "lede_dupes": [{"section": "national",
                            "duplicate_of": "front lead"}],
        })

    briefing, _ = await _assemble_with_fakes(
        gen_panel=gen_panel, gen_briefs_result=_briefs8,
        generate_editor=gen_editor,
    )
    nat = [p for p in briefing.panels if p.section == "National"][0]
    assert nat.lede_headline == "National lede"   # original kept
    assert len(nat.also) == 4                     # still trimmed


def test_apply_cuts_pure():
    panels = [_panel6("National")]
    briefs = _briefs8()
    decision = EditorDecision.model_validate({
        "cuts": [{"section": "national", "index": 1},
                 {"section": "national", "index": 4},
                 {"section": "briefs", "index": 0},
                 {"section": "briefs", "index": 7}],
        "lede_dupes": [],
    })
    new_panels, new_briefs = _apply_cuts(decision, ["national"], panels, briefs)
    assert [it.headline for it in new_panels[0].also] == \
        ["National H0", "National H2", "National H3", "National H5"]
    assert [b.topic for b in new_briefs] == [f"T{i}" for i in range(1, 7)]


def test_trim_positional_pure():
    panels, briefs = _trim_positional([_panel6("National")], _briefs8())
    assert len(panels[0].also) == 4 and len(briefs) == 6
    # already-final input is a no-op
    panels2, briefs2 = _trim_positional(panels, briefs)
    assert panels2[0].also == panels[0].also and briefs2 == briefs
