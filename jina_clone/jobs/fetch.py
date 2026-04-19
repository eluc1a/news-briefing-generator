import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from jina_clone.config import Source
from jina_clone.extractor.core import ExtractResult
from jina_clone.sources.rss import DiscoveredItem
from jina_clone.storage.db import insert_entry, link_exists

log = logging.getLogger(__name__)

RssFetcher = Callable[..., Awaitable[list[DiscoveredItem]]]
ScrapeFetcher = Callable[..., Awaitable[list[DiscoveredItem]]]
Extractor = Callable[..., Awaitable[ExtractResult]]


async def run_fetch(
    pool,
    *,
    sources: list[Source],
    rss_fetcher: RssFetcher,
    scrape_fetcher: ScrapeFetcher,
    extract: Extractor,
    delay_seconds: float = 1.0,
    request_timeout: int = 15,
    max_text_length: int = 4000,
    window_hours: float = 24.0,
) -> dict[str, dict[str, int]]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    stats: dict[str, dict[str, int]] = {}
    for source in sources:
        s = {"new": 0, "errors": 0, "skipped": 0, "failed": 0, "out_of_window": 0}
        stats[source.name] = s
        try:
            if source.type == "rss":
                items = await rss_fetcher(source.url, timeout=request_timeout)
            else:
                items = await scrape_fetcher(
                    source.url, selector=source.link_selector, timeout=request_timeout
                )
        except Exception as exc:
            log.warning("discovery failed for %s: %s", source.name, exc)
            s["failed"] = 1
            continue

        in_window: list[DiscoveredItem] = []
        for item in items:
            if item.published is not None and item.published < cutoff:
                s["out_of_window"] += 1
                continue
            in_window.append(item)
        log.info(
            "discovered %d items from %s (%d in %sh window)",
            len(items), source.name, len(in_window), window_hours,
        )
        for item in in_window:
            if await link_exists(pool, item.url):
                s["skipped"] += 1
                continue
            result = await extract(
                item.url, timeout=request_timeout, max_length=max_text_length
            )
            if result.error is not None:
                log.warning("extraction error %s: %s", item.url, result.error)
                s["errors"] += 1
            else:
                s["new"] += 1
                log.info("stored %s", result.title)
            await insert_entry(
                pool,
                url=item.url,
                title=result.title,
                source=source.name,
                category=source.category,
                content=result.text,
                published=item.published,
            )
            if delay_seconds > 0:
                await asyncio.sleep(delay_seconds)
    return stats
