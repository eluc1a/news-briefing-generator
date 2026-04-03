import os
import re

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from fastapi import FastAPI
from readability import Document

load_dotenv()

PORT = int(os.getenv("PORT", 8080))
MAX_TEXT_LENGTH = int(os.getenv("MAX_TEXT_LENGTH", 4000))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", 15))

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

app = FastAPI()


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/extract")
async def extract(url: str):
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            response = await client.get(url)

        content_type = response.headers.get("content-type", "")
        if "text/html" not in content_type:
            return {
                "url": url,
                "title": None,
                "text": None,
                "error": f"Unsupported content type: {content_type}",
            }

        doc = Document(response.text)
        title = doc.title()
        article_html = doc.summary()

        soup = BeautifulSoup(article_html, "html.parser")
        raw_text = soup.get_text(separator=" ")
        text = re.sub(r"\s+", " ", raw_text).strip()
        text = text[:MAX_TEXT_LENGTH]

        return {"url": url, "title": title, "text": text, "error": None}

    except Exception as exc:
        return {"url": url, "title": None, "text": None, "error": str(exc)}
