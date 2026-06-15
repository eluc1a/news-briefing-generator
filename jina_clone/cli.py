import argparse
import asyncio
import logging
import os
import tempfile
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
from jina_clone.briefing import feed as briefing_feed
from jina_clone.briefing.config import load_briefing_config
from jina_clone.briefing.schema import Briefing, WeatherStrip
from jina_clone.briefing.web import make_render_and_save_json, rebuild_index
from jina_clone.jobs.briefing import WeatherFn, MarketsFn, assemble_briefing, run_briefing
from jina_clone.jobs.slack_digest import run_slack_digest
from jina_clone.storage.db import (
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


_CACHE_DIR = Path("cache")
_WEATHER_CACHE = _CACHE_DIR / "weather.json"


def _stub_weather_dict() -> dict:
    """Last-resort fallback when the OWM key is unset AND no cache
    exists. Shape matches live_data.fetch_weather's return."""
    return {
        "temp_high": 68, "temp_low": 48,
        "conditions": "partly cloudy",
        "sunrise": "6:24", "sunset": "7:48",
        "daylight": "13h 24m",
        "hourly": {"slots": [
            {"time_label": "11am", "temp_f": 62, "precip_pct": 10, "code": 800},
            {"time_label": "2pm",  "temp_f": 68, "precip_pct": 20, "code": 801},
            {"time_label": "5pm",  "temp_f": 71, "precip_pct": 40, "code": 802},
            {"time_label": "8pm",  "temp_f": 60, "precip_pct": 20, "code": 803},
        ]},
    }


def _make_weather_provider(settings: Settings) -> WeatherFn:
    """Returns an async callable matching jobs.briefing.WeatherFn."""
    from jina_clone.briefing.live_data import fetch_weather

    async def provider() -> dict:
        return await fetch_weather(
            cache_path=_WEATHER_CACHE,
            owm_api_key=settings.weather_api_key,
            stub=_stub_weather_dict,
        )
    return provider


def _make_markets_provider(settings: Settings) -> MarketsFn:
    """Returns an async callable matching jobs.briefing.MarketsFn."""
    from jina_clone.briefing.live_data import fetch_markets

    async def provider() -> dict:
        return await fetch_markets(
            finnhub_api_key=settings.stock_api_key,
            fred_api_key=settings.fred_api_key,
        )
    return provider


def _today_label() -> str:
    return datetime.now().strftime("%A, %B %-d, %Y · %-I:%M %p")


def _volume_label(today: date) -> str:
    return f"Vol. I · No. {(today - date(2026, 1, 1)).days + 1}"


async def _briefing_generate(settings, out_path: Path):
    cfg = load_briefing_config(settings.briefing_categories_file)
    pool = await create_pool(settings.database_url)
    try:
        briefing, _count = await assemble_briefing(
            pool=pool,
            config=cfg,
            window_hours=12,
            title="The Morning Fox",
            weather_provider=_make_weather_provider(settings),
            markets_provider=_make_markets_provider(settings),
            today_label=_today_label(),
            volume_label=_volume_label(date.today()),
            iso_date=date.today().isoformat(),
            fetch_articles=fetch_section_articles,
            generate_front_matter=briefing_generator.generate_front_matter,
            generate_panel=briefing_generator.generate_panel,
            generate_briefs=briefing_generator.generate_briefs,
        )
    finally:
        await pool.close()

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
    briefing_notify.notify_printed(topic=settings.ntfy_topic, title="The Morning Fox", pages=2)


EDITION_TITLES = {
    "morning": "The Morning Fox",
    "evening": "The Evening Fox",
}

# Non-overlapping windows matching the cron cadence (8:45 / 16:30 ET —
# 15 min before the 9:00/16:45 channel targets, absorbing Slack's
# feed-poll lag): morning covers since yesterday 16:30, afternoon
# covers since 8:45.
SLACK_DIGEST_WINDOWS = {"morning": 16.25, "afternoon": 7.75}
SLACK_DIGEST_EDITION_LABELS = {"morning": "Morning", "afternoon": "Afternoon"}
SLACK_DIGEST_TITLE = "AI/ML Slack Digest"
SLACK_DIGEST_DRY_RUN_BASE_URL = "https://example.invalid/ai-digest"


async def _briefing_run(settings, *, edition: str):
    cfg = load_briefing_config(settings.briefing_categories_file)
    title = EDITION_TITLES[edition]
    today = date.today()
    iso_date = today.isoformat()
    pdf_path = settings.briefings_dir / f"{iso_date}-{edition}.pdf"
    volume_label = f"{_volume_label(today)} · {edition.title()}"

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
            render=make_render_and_save_json(
                briefing_renderer.render_pdf,
                briefings_dir=settings.briefings_dir,
                edition=edition,
            ),
            print_pdf=briefing_printer.print_pdf,
            notify_printed=briefing_notify.notify_printed,
            notify_failure=briefing_notify.notify_failure,
            insert_summary=insert_summary,
            emergency_path=Path(__file__).parent / "briefing" / "fixtures" / "emergency.json",
        )
    finally:
        await pool.close()
        totals = briefing_generator.pop_usage_totals()
        if totals["calls"]:
            logging.info(
                "briefing llm totals (%s %s): calls=%d input=%d output=%d "
                "cache_read=%d cache_creation=%d",
                iso_date, edition,
                totals["calls"], totals["input"], totals["output"],
                totals["cache_read"], totals["cache_creation"],
            )


def _briefing_publish_web(settings: Settings) -> None:
    """Downstream web-publish step: rebuild index.json from the edition
    JSONs the print run dropped. No LLM, no print, no DB — safe to run on
    its own cron, decoupled from the print briefing."""
    index_path = rebuild_index(settings.briefings_dir)
    logging.info("rebuilt web index: %s", index_path)


async def _run_slack_digest(settings: Settings, *, edition: str, dry_run: bool):
    if not settings.feed_base_url and not dry_run:
        raise SystemExit(
            "FEED_BASE_URL is required for slack-digest (set it in .env)"
        )
    cfg = load_briefing_config(settings.briefing_categories_file)

    tmp = None
    out_dir = settings.feed_output_dir
    if dry_run:
        tmp = tempfile.TemporaryDirectory(prefix="ai-digest-dryrun-")
        out_dir = Path(tmp.name)
    base_url = (settings.feed_base_url or SLACK_DIGEST_DRY_RUN_BASE_URL).rstrip("/")

    now = datetime.now().astimezone()
    iso_date = now.date().isoformat()
    edition_label = SLACK_DIGEST_EDITION_LABELS[edition]
    date_label = now.strftime("%a %b %-d")
    generated_at = now

    def publish(digest):
        return briefing_feed.publish_digest(
            digest, out_dir=out_dir, base_url=base_url, iso_date=iso_date,
            edition=edition, edition_label=edition_label,
            date_label=date_label, generated_at=generated_at,
        )

    def publish_fallback(articles):
        return briefing_feed.publish_fallback(
            articles, out_dir=out_dir, base_url=base_url, iso_date=iso_date,
            edition=edition, edition_label=edition_label,
            date_label=date_label, generated_at=generated_at,
        )

    briefing_generator.reset_usage()
    pool = await create_pool(settings.database_url)
    try:
        await run_slack_digest(
            pool,
            window_hours=SLACK_DIGEST_WINDOWS[edition],
            edition_label=edition_label,
            title=SLACK_DIGEST_TITLE,
            ntfy_topic=settings.ntfy_topic,
            source_caps=dict(cfg.source_caps),
            fetch_articles=fetch_section_articles,
            generate_digest=briefing_generator.generate_slack_digest,
            publish=publish,
            publish_fallback=publish_fallback,
            notify_failure=briefing_notify.notify_failure,
        )
        if dry_run:
            page = out_dir / f"{iso_date}-{edition}.html"
            if page.exists():
                print(page.read_text())
                print((out_dir / "feed.xml").read_text())
            else:
                print("(no articles in window — nothing rendered)")
    finally:
        if tmp is not None:
            tmp.cleanup()
        await pool.close()
        totals = briefing_generator.pop_usage_totals()
        if totals["calls"]:
            logging.info(
                "slack digest llm totals (%s): calls=%d input=%d output=%d "
                "cache_read=%d cache_creation=%d",
                edition,
                totals["calls"], totals["input"], totals["output"],
                totals["cache_read"], totals["cache_creation"],
            )


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

    run_p = briefing_sub.add_parser("run")
    run_p.add_argument(
        "--edition",
        required=True,
        choices=["morning", "evening"],
        help="Which edition to produce: morning (08:10 ET) or evening (20:10 ET).",
    )

    briefing_sub.add_parser(
        "publish-web",
        help="Rebuild briefings/index.json from on-disk editions (downstream web publish).",
    )

    slack_p = sub.add_parser("slack-digest")
    slack_p.add_argument(
        "--edition", required=True, choices=["morning", "afternoon"],
        help="morning (8:45 ET, 16.25h window) or afternoon (16:30 ET, 7.75h window)",
    )
    slack_p.add_argument(
        "--dry-run", action="store_true",
        help="Print the rendered page HTML + feed XML to stdout; write nothing",
    )

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
            asyncio.run(_briefing_run(settings, edition=args.edition))
        elif args.action == "publish-web":
            _briefing_publish_web(settings)
    elif args.cmd == "slack-digest":
        asyncio.run(
            _run_slack_digest(settings, edition=args.edition, dry_run=args.dry_run)
        )


if __name__ == "__main__":
    main()
