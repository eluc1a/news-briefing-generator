import re
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup
from readability import Document

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


@dataclass
class ExtractResult:
    url: str
    title: str | None
    text: str | None
    error: str | None


def extract_from_html(html: str, max_length: int | None = None) -> dict:
    """Pure extraction: HTML string -> {'title', 'text'}. No I/O."""
    doc = Document(html)
    summary_html = doc.summary()
    soup = BeautifulSoup(summary_html, "html.parser")
    for tag in soup.find_all(["nav", "footer", "header", "aside"]):
        tag.decompose()
    heading = soup.find(re.compile(r"^h[1-6]$"))
    title = heading.get_text().strip() if heading else doc.title()
    raw_text = soup.get_text(separator=" ")
    text = re.sub(r"\s+", " ", raw_text).strip()
    if max_length is not None:
        text = text[:max_length]
    return {"title": title, "text": text}


async def extract_article(
    url: str,
    *,
    timeout: int = 15,
    max_length: int | None = 4000,
    user_agent: str = DEFAULT_USER_AGENT,
) -> ExtractResult:
    """Fetch URL and extract. Never raises — returns ExtractResult with error set on failure."""
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": user_agent},
        ) as client:
            response = await client.get(url)
        if response.status_code >= 400:
            return ExtractResult(
                url=url, title=None, text=None,
                error=f"HTTP {response.status_code}",
            )
        content_type = response.headers.get("content-type", "")
        if "text/html" not in content_type:
            return ExtractResult(
                url=url, title=None, text=None,
                error=f"Unsupported content type: {content_type}",
            )
        parsed = extract_from_html(response.text, max_length=max_length)
        return ExtractResult(url=url, title=parsed["title"], text=parsed["text"], error=None)
    except Exception as exc:
        return ExtractResult(url=url, title=None, text=None, error=str(exc))
