import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_PROVIDER_KEY = {
    "claude": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


@dataclass
class Source:
    name: str
    type: str
    url: str
    category: str
    link_selector: str | None = None


@dataclass
class Settings:
    database_url: str
    sources_file: Path
    summaries_dir: Path
    fetch_concurrency: int
    fetch_delay_seconds: float
    request_timeout: int
    max_text_length: int
    llm_provider: str
    llm_model: str | None
    api_keys: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "Settings":
        provider = os.getenv("LLM_PROVIDER", "claude")
        if provider not in _PROVIDER_KEY:
            raise ValueError(f"Unknown LLM_PROVIDER: {provider}")
        key_name = _PROVIDER_KEY[provider]
        api_key = os.getenv(key_name)
        if not api_key:
            raise ValueError(f"{key_name} is required for LLM_PROVIDER={provider}")
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise ValueError("DATABASE_URL is required")
        return cls(
            database_url=database_url,
            sources_file=Path(os.getenv("SOURCES_FILE", "sources.yaml")),
            summaries_dir=Path(os.getenv("SUMMARIES_DIR", "summaries")),
            fetch_concurrency=int(os.getenv("FETCH_CONCURRENCY", "4")),
            fetch_delay_seconds=float(os.getenv("FETCH_DELAY_SECONDS", "1")),
            request_timeout=int(os.getenv("REQUEST_TIMEOUT", "15")),
            max_text_length=int(os.getenv("MAX_TEXT_LENGTH", "4000")),
            llm_provider=provider,
            llm_model=os.getenv("LLM_MODEL") or None,
            api_keys={key_name: api_key},
        )


def load_sources(path: Path) -> list[Source]:
    data = yaml.safe_load(Path(path).read_text())
    raw = data.get("sources", [])
    sources: list[Source] = []
    for i, item in enumerate(raw):
        if "type" not in item or item["type"] not in ("rss", "scrape"):
            raise ValueError(f"Unknown source type in entry {i}: {item.get('type')!r}")
        if item["type"] == "scrape" and not item.get("link_selector"):
            raise ValueError(f"scrape source {item.get('name', i)!r} missing link_selector")
        sources.append(
            Source(
                name=item["name"],
                type=item["type"],
                url=item["url"],
                category=item.get("category", "ai"),
                link_selector=item.get("link_selector"),
            )
        )
    return sources
