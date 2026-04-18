from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from jina_clone.sources.rss import DiscoveredItem


def parse_index(html: str, *, base_url: str, selector: str) -> list[DiscoveredItem]:
    soup = BeautifulSoup(html, "html.parser")
    items: list[DiscoveredItem] = []
    for a in soup.select(selector):
        href = a.get("href")
        if not href:
            continue
        absolute = urljoin(base_url, href)
        items.append(DiscoveredItem(url=absolute, published=None))
    return items


async def fetch_index(url: str, *, selector: str, timeout: int = 15) -> list[DiscoveredItem]:
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        response = await client.get(url)
    return parse_index(response.text, base_url=url, selector=selector)
