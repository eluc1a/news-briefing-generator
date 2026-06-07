"""Web-publishing variant of `briefing run`.

Invoked by host cron instead of `python -m jina_clone briefing run`. It
reuses the existing run_briefing orchestration (emergency fallback, ntfy,
news_summaries logging) unchanged, but injects a render wrapper that also
writes the briefing JSON + index.json for themorningfox.com. Existing code
is not modified — this is an additive entry point.
"""
import argparse
import asyncio
import logging
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv

from jina_clone.briefing import generator as briefing_generator
from jina_clone.briefing import notify as briefing_notify
from jina_clone.briefing import printer as briefing_printer
from jina_clone.briefing import renderer as briefing_renderer
from jina_clone.briefing.config import load_briefing_config
from jina_clone.briefing.web import make_render_and_publish
from jina_clone.cli import (
    EDITION_TITLES,
    _make_markets_provider,
    _make_weather_provider,
    _setup_logging,
    _today_label,
    _volume_label,
)
from jina_clone.config import Settings
from jina_clone.jobs.briefing import run_briefing
from jina_clone.storage.db import create_pool, fetch_section_articles, insert_summary

log = logging.getLogger(__name__)


async def _run_web(settings: Settings, *, edition: str) -> None:
    cfg = load_briefing_config(settings.briefing_categories_file)
    title = EDITION_TITLES[edition]
    today = date.today()
    iso_date = today.isoformat()
    pdf_path = settings.briefings_dir / f"{iso_date}-{edition}.pdf"
    volume_label = f"{_volume_label(today)} · {edition.title()}"

    render = make_render_and_publish(
        briefing_renderer.render_pdf,
        briefings_dir=settings.briefings_dir,
        edition=edition,
    )

    briefing_generator.reset_usage()
    pool = await create_pool(settings.database_url)
    try:
        await run_briefing(
            pool=pool,
            config=cfg,
            window_hours=12,
            title=title,
            pdf_path=pdf_path,
            print_queue=settings.print_queue,
            ntfy_topic=settings.ntfy_topic,
            weather_provider=_make_weather_provider(settings),
            markets_provider=_make_markets_provider(settings),
            today_label=_today_label(),
            volume_label=volume_label,
            generated_at_label=datetime.now().strftime("%H:%M ET"),
            iso_date=iso_date,
            fetch_articles=fetch_section_articles,
            generate_front_matter=briefing_generator.generate_front_matter,
            generate_panel=briefing_generator.generate_panel,
            generate_briefs=briefing_generator.generate_briefs,
            render=render,
            print_pdf=briefing_printer.print_pdf,
            notify_printed=briefing_notify.notify_printed,
            notify_failure=briefing_notify.notify_failure,
            insert_summary=insert_summary,
            emergency_path=Path(__file__).parent / "fixtures" / "emergency.json",
        )
    finally:
        await pool.close()
        totals = briefing_generator.pop_usage_totals()
        if totals["calls"]:
            log.info(
                "briefing llm totals (%s %s): calls=%d input=%d output=%d "
                "cache_read=%d cache_creation=%d",
                iso_date, edition,
                totals["calls"], totals["input"], totals["output"],
                totals["cache_read"], totals["cache_creation"],
            )


def main() -> None:
    load_dotenv()
    _setup_logging()
    parser = argparse.ArgumentParser(prog="jina_clone.briefing.run_web")
    parser.add_argument("--edition", required=True, choices=["morning", "evening"])
    args = parser.parse_args()
    settings = Settings.from_env()
    asyncio.run(_run_web(settings, edition=args.edition))


if __name__ == "__main__":
    main()
