import argparse
import asyncio
import logging
import os
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv

from jina_clone.config import Settings, load_sources
from jina_clone.extractor.core import extract_article
from jina_clone.jobs.fetch import run_fetch
from jina_clone.jobs.summarize import run_summarize
from jina_clone.sources.rss import fetch_feed
from jina_clone.sources.scrape import fetch_index
from jina_clone.storage.db import create_pool
from jina_clone.summarizer.providers import build_provider
from jina_clone.briefing import generator as briefing_generator
from jina_clone.briefing import notify as briefing_notify
from jina_clone.briefing import printer as briefing_printer
from jina_clone.briefing import renderer as briefing_renderer
from jina_clone.briefing.config import load_briefing_config
from jina_clone.briefing.schema import Briefing, WeatherStrip
from jina_clone.jobs.briefing import run_briefing
from jina_clone.storage.db import (
    fetch_recent_articles_by_category,
    fetch_section_articles,
    insert_summary,
)


def _setup_logging():
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level_name, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def _run_fetch(settings: Settings):
    sources = load_sources(settings.sources_file)
    pool = await create_pool(settings.database_url)
    try:
        stats = await run_fetch(
            pool,
            sources=sources,
            rss_fetcher=fetch_feed,
            scrape_fetcher=fetch_index,
            extract=extract_article,
            delay_seconds=settings.fetch_delay_seconds,
            request_timeout=settings.request_timeout,
            max_text_length=settings.max_text_length,
            window_hours=settings.fetch_window_hours,
        )
        for name, s in stats.items():
            logging.info(
                "%s: %d new, %d errors, %d skipped, %d out-of-window, %d failed",
                name,
                s["new"],
                s["errors"],
                s["skipped"],
                s.get("out_of_window", 0),
                s.get("failed", 0),
            )
    finally:
        await pool.close()


async def _run_summarize(settings: Settings):
    sources = load_sources(settings.sources_file)
    by_category: dict[str, list[str]] = {}
    for s in sources:
        by_category.setdefault(s.category, []).append(s.name)
    provider = build_provider(settings)
    pool = await create_pool(settings.database_url)
    try:
        for category, names in sorted(by_category.items()):
            result = await run_summarize(
                pool,
                source_names=names,
                provider=provider,
                summaries_dir=settings.summaries_dir,
                category=category,
                token_cap=settings.summary_token_cap,
                window_hours=settings.summary_window_hours,
            )
            if result:
                logging.info("summary written: %s", result["output_path"])
    finally:
        await pool.close()


def _stub_weather() -> dict:
    # Phase-1 stub. Real NWS integration is deferred (see spec §17 / Risks).
    return {
        "temp_high": 68, "temp_low": 48,
        "conditions": "partly cloudy",
        "sunrise": "6:24", "sunset": "7:48",
        "pollen": "moderate",
    }


def _today_label() -> str:
    return datetime.now().strftime("%A, %B %-d, %Y")


def _volume_label(today: date) -> str:
    return f"Vol. I · No. {(today - date(2026, 1, 1)).days + 1}"


async def _briefing_generate(settings, out_path: Path):
    cfg = load_briefing_config(settings.briefing_categories_file)
    pool = await create_pool(settings.database_url)
    try:
        section_pools: dict[str, list[dict]] = {}
        for s in cfg.sections:
            rows = await fetch_section_articles(
                pool, categories=list(s.categories),
                per_source_cap=cfg.per_source_cap, limit=s.limit,
            )
            section_pools[s.key] = [dict(r) for r in rows]
        briefs_rows = await fetch_section_articles(
            pool, categories=list(cfg.briefs.categories),
            per_source_cap=cfg.per_source_cap, limit=cfg.briefs.limit,
        )
        briefs_pool = [dict(r) for r in briefs_rows]
    finally:
        await pool.close()

    # Build front-matter input pool (dedupe on link)
    seen: set[str] = set()
    front_pool: list[dict] = []
    for s in cfg.sections:
        for a in section_pools[s.key][: cfg.front_matter_top_per_section]:
            if a["link"] in seen:
                continue
            seen.add(a["link"])
            front_pool.append(a)

    weather = _stub_weather()
    today = _today_label()
    volume = _volume_label(date.today())

    front = await briefing_generator.generate_front_matter(
        articles=front_pool, weather=weather, today=today, volume=volume,
    )
    exclude = {front.lead_source_url}

    import asyncio
    panels_and_briefs = await asyncio.gather(
        *[
            briefing_generator.generate_panel(
                section=s, articles=section_pools[s.key], exclude_urls=exclude,
            )
            for s in cfg.sections
        ],
        briefing_generator.generate_briefs(
            articles=briefs_pool, exclude_urls=exclude,
        ),
    )
    panels = list(panels_and_briefs[:-1])
    briefs = panels_and_briefs[-1]

    briefing = Briefing(
        date=date.today().isoformat(),
        volume=volume,
        weather=WeatherStrip(**weather),
        lead=front.lead,
        panels=panels,
        pull_quote=front.pull_quote,
        briefs=briefs,
        data_point=front.data_point,
        on_this_day=front.on_this_day,
    )
    out_path.write_text(briefing.model_dump_json(indent=2))
    logging.info("wrote %s", out_path)


def _briefing_render(input_path: Path, out_path: Path):
    briefing = Briefing.model_validate_json(input_path.read_text())
    briefing_renderer.render_pdf(
        briefing, out_path,
        generated_at=datetime.now().strftime("%H:%M ET"),
        iso_date=date.today().isoformat(),
    )
    logging.info("wrote %s", out_path)


def _briefing_print(settings, pdf_path: Path):
    msg = briefing_printer.print_pdf(pdf_path, queue=settings.print_queue)
    logging.info("print: %s", msg)
    briefing_notify.notify_printed(topic=settings.ntfy_topic, pages=2)


async def _briefing_run(settings):
    cfg = load_briefing_config(settings.briefing_categories_file)
    pool = await create_pool(settings.database_url)
    try:
        await run_briefing(
            pool=pool,
            config=cfg,
            briefings_dir=settings.briefings_dir,
            print_queue=settings.print_queue,
            ntfy_topic=settings.ntfy_topic,
            weather_provider=_stub_weather,
            today_label=_today_label(),
            volume_label=_volume_label(date.today()),
            generated_at_label=datetime.now().strftime("%H:%M ET"),
            iso_date=date.today().isoformat(),
            fetch_articles=fetch_section_articles,
            generate_front_matter=briefing_generator.generate_front_matter,
            generate_panel=briefing_generator.generate_panel,
            generate_briefs=briefing_generator.generate_briefs,
            render=briefing_renderer.render_pdf,
            print_pdf=briefing_printer.print_pdf,
            notify_printed=briefing_notify.notify_printed,
            notify_failure=briefing_notify.notify_failure,
            insert_summary=insert_summary,
            emergency_path=Path(__file__).parent / "briefing" / "fixtures" / "emergency.json",
        )
    finally:
        await pool.close()


def main():
    load_dotenv()
    _setup_logging()
    parser = argparse.ArgumentParser(prog="jina_clone")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch")
    sub.add_parser("summarize")

    briefing_p = sub.add_parser("briefing")
    briefing_sub = briefing_p.add_subparsers(dest="action", required=True)

    gen_p = briefing_sub.add_parser("generate")
    gen_p.add_argument("--out", type=Path,
                       default=Path(f"/tmp/briefing-{date.today().isoformat()}.json"))

    rend_p = briefing_sub.add_parser("render")
    rend_p.add_argument("input", type=Path)
    rend_p.add_argument("--out", type=Path,
                        default=Path(f"/tmp/briefing-{date.today().isoformat()}.pdf"))

    print_p = briefing_sub.add_parser("print")
    print_p.add_argument("pdf", type=Path)

    briefing_sub.add_parser("run")

    args = parser.parse_args()
    settings = Settings.from_env()

    if args.cmd == "fetch":
        asyncio.run(_run_fetch(settings))
    elif args.cmd == "summarize":
        asyncio.run(_run_summarize(settings))
    elif args.cmd == "briefing":
        if args.action == "generate":
            asyncio.run(_briefing_generate(settings, args.out))
        elif args.action == "render":
            _briefing_render(args.input, args.out)
        elif args.action == "print":
            _briefing_print(settings, args.pdf)
        elif args.action == "run":
            asyncio.run(_briefing_run(settings))


if __name__ == "__main__":
    main()
