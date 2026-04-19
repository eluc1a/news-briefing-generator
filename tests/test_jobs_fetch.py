from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from jina_clone.config import Source
from jina_clone.extractor.core import ExtractResult
from jina_clone.jobs.fetch import run_fetch
from jina_clone.sources.rss import DiscoveredItem


@dataclass
class FakeDiscoverer:
    per_source: dict[str, list[DiscoveredItem]]

    async def rss(self, url, *, timeout=15):
        return self.per_source[url]

    async def scrape(self, url, *, selector, timeout=15):
        return self.per_source[url]


class FakeExtractor:
    def __init__(self):
        self.calls: list[str] = []

    async def extract(self, url, *, timeout=15, max_length=4000):
        self.calls.append(url)
        if "bad" in url:
            return ExtractResult(url=url, title=None, text=None, error="boom")
        return ExtractResult(url=url, title=f"Title {url}", text=f"Body {url}", error=None)


async def test_run_fetch_stores_new_articles_skips_seen_and_records_errors(db):
    sources = [
        Source(name="Feed", type="rss", url="https://feed.example/a", category="ai"),
        Source(name="Scraped", type="scrape", url="https://site.example/",
               category="ai", link_selector="a"),
    ]
    disc = FakeDiscoverer(per_source={
        "https://feed.example/a": [
            DiscoveredItem(url="https://feed.example/1", published=None),
            DiscoveredItem(url="https://feed.example/bad", published=None),
        ],
        "https://site.example/": [
            DiscoveredItem(url="https://site.example/2", published=None),
        ],
    })
    extractor = FakeExtractor()

    stats = await run_fetch(
        db,
        sources=sources,
        rss_fetcher=disc.rss,
        scrape_fetcher=disc.scrape,
        extract=extractor.extract,
        delay_seconds=0,
    )

    assert stats["Feed"]["new"] == 1
    assert stats["Feed"]["errors"] == 1
    assert stats["Scraped"]["new"] == 1

    # Second run: all seen → no new extraction calls
    extractor.calls.clear()
    stats2 = await run_fetch(
        db, sources=sources,
        rss_fetcher=disc.rss, scrape_fetcher=disc.scrape,
        extract=extractor.extract, delay_seconds=0,
    )
    assert extractor.calls == []
    assert stats2["Feed"]["skipped"] == 2


async def test_run_fetch_skips_items_older_than_window(db):
    now = datetime.now(timezone.utc)
    sources = [Source(name="Feed", type="rss", url="https://feed.example/a", category="ai")]
    disc = FakeDiscoverer(per_source={
        "https://feed.example/a": [
            DiscoveredItem(url="https://feed.example/fresh", published=now - timedelta(hours=1)),
            DiscoveredItem(url="https://feed.example/stale", published=now - timedelta(hours=48)),
            DiscoveredItem(url="https://feed.example/notimestamp", published=None),
        ],
    })
    extractor = FakeExtractor()

    stats = await run_fetch(
        db,
        sources=sources,
        rss_fetcher=disc.rss,
        scrape_fetcher=disc.scrape,
        extract=extractor.extract,
        delay_seconds=0,
        window_hours=24.0,
    )

    assert stats["Feed"]["new"] == 2  # fresh + notimestamp
    assert stats["Feed"]["out_of_window"] == 1
    assert "https://feed.example/stale" not in extractor.calls
