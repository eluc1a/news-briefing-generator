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
    fetch_window_hours: float
    request_timeout: int
    max_text_length: int
    llm_provider: str
    llm_model: str | None
    summary_token_cap: int
    summary_window_hours: float
    briefing_categories_file: Path
    briefings_dir: Path
    print_queue: str
    ntfy_topic: str | None
    weather_api_key: str = ""
    stock_api_key: str = ""
    fred_api_key: str = ""
    slack_webhook_url: str | None = None
    api_keys: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "Settings":
        provider = os.getenv("LLM_PROVIDER", "claude")
        if provider not in _PROVIDER_KEY:
            raise ValueError(f"Unknown LLM_PROVIDER: {provider}")
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise ValueError("DATABASE_URL is required")
        api_keys = {name: val for name in _PROVIDER_KEY.values() if (val := os.getenv(name))}
        weather_api_key = os.getenv("WEATHER_API_KEY", "")
        stock_api_key = os.getenv("STOCK_API_KEY", "")
        fred_api_key = os.getenv("FRED_API_KEY", "")
        return cls(
            database_url=database_url,
            sources_file=Path(os.getenv("SOURCES_FILE", "sources.yaml")),
            summaries_dir=Path(os.getenv("SUMMARIES_DIR", "summaries")),
            fetch_concurrency=int(os.getenv("FETCH_CONCURRENCY", "4")),
            fetch_delay_seconds=float(os.getenv("FETCH_DELAY_SECONDS", "1")),
            fetch_window_hours=float(os.getenv("FETCH_WINDOW_HOURS", "24")),
            request_timeout=int(os.getenv("REQUEST_TIMEOUT", "15")),
            max_text_length=int(os.getenv("MAX_TEXT_LENGTH", "4000")),
            llm_provider=provider,
            llm_model=os.getenv("LLM_MODEL") or None,
            summary_token_cap=int(os.getenv("SUMMARY_TOKEN_CAP", "850000")),
            summary_window_hours=float(os.getenv("SUMMARY_WINDOW_HOURS", "24")),
            briefing_categories_file=Path(
                os.getenv("BRIEFING_CATEGORIES_FILE", "config/briefing_categories.yaml")
            ),
            briefings_dir=Path(os.getenv("BRIEFINGS_DIR", "briefings")),
            print_queue=os.getenv("PRINT_QUEUE", "brother"),
            ntfy_topic=os.getenv("NTFY_TOPIC") or None,
            weather_api_key=weather_api_key,
            stock_api_key=stock_api_key,
            fred_api_key=fred_api_key,
            slack_webhook_url=os.getenv("SLACK_WEBHOOK_URL") or None,
            api_keys=api_keys,
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
