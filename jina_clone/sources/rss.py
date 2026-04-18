from dataclasses import dataclass
from datetime import datetime, timezone
from time import mktime

import feedparser
import httpx


@dataclass
class DiscoveredItem:
    url: str
    published: datetime | None


def parse_feed(xml_or_bytes) -> list[DiscoveredItem]:
    parsed = feedparser.parse(xml_or_bytes)
    items: list[DiscoveredItem] = []
    for entry in parsed.entries:
        link = entry.get("link")
        if not link:
            continue
        published = None
        if entry.get("published_parsed"):
            published = datetime.fromtimestamp(
                mktime(entry.published_parsed), tz=timezone.utc
            )
        items.append(DiscoveredItem(url=link, published=published))
    return items


async def fetch_feed(url: str, *, timeout: int = 15) -> list[DiscoveredItem]:
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        response = await client.get(url)
    return parse_feed(response.text)
