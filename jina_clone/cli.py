import argparse
import asyncio
import logging
import os

from dotenv import load_dotenv

from jina_clone.config import Settings, load_sources
from jina_clone.extractor.core import extract_article
from jina_clone.jobs.fetch import run_fetch
from jina_clone.jobs.summarize import run_summarize
from jina_clone.sources.rss import fetch_feed
from jina_clone.sources.scrape import fetch_index
from jina_clone.storage.db import create_pool
from jina_clone.summarizer.providers import build_provider


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
        )
        for name, s in stats.items():
            logging.info(
                "%s: %d new, %d errors, %d skipped, %d failed",
                name,
                s["new"],
                s["errors"],
                s["skipped"],
                s.get("failed", 0),
            )
    finally:
        await pool.close()


async def _run_summarize(settings: Settings):
    sources = load_sources(settings.sources_file)
    our_names = [s.name for s in sources]
    provider = build_provider(settings)
    pool = await create_pool(settings.database_url)
    try:
        result = await run_summarize(
            pool,
            source_names=our_names,
            provider=provider,
            summaries_dir=settings.summaries_dir,
            category="ai",
        )
        if result:
            logging.info("summary written: %s", result["output_path"])
    finally:
        await pool.close()


def main():
    load_dotenv()
    _setup_logging()
    parser = argparse.ArgumentParser(prog="jina_clone")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch")
    sub.add_parser("summarize")
    args = parser.parse_args()

    settings = Settings.from_env()
    if args.cmd == "fetch":
        asyncio.run(_run_fetch(settings))
    elif args.cmd == "summarize":
        asyncio.run(_run_summarize(settings))


if __name__ == "__main__":
    main()
