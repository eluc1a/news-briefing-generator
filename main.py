import os

from dotenv import load_dotenv
from fastapi import FastAPI

from jina_clone.extractor.core import extract_article

load_dotenv()

PORT = int(os.getenv("PORT", 8080))
MAX_TEXT_LENGTH = int(os.getenv("MAX_TEXT_LENGTH", 4000))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", 15))

app = FastAPI()


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/extract")
async def extract(url: str):
    result = await extract_article(
        url, timeout=REQUEST_TIMEOUT, max_length=MAX_TEXT_LENGTH
    )
    return {
        "url": result.url,
        "title": result.title,
        "text": result.text,
        "error": result.error,
    }
