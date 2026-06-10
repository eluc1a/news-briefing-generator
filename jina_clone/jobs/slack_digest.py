"""Slack digest job: fetch AI articles → LLM digest → publish RSS feed.

Delivery is a public RSS feed Slack's /feed app polls — no app-install
rights in the work workspace, so no webhook/bot (2026-06-09 RSS spec).

Failure policy:
- LLM failure → publish a headlines-only fallback entry, then ntfy
  (degraded, not silent — the channel still gets links).
- Publish (file write) failure → ntfy, then re-raise so the cron log
  records it.
- Zero articles in window → no entry, no ntfy (quiet windows are normal).
"""
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

from jina_clone.briefing.generator import GeneratorFailure

log = logging.getLogger(__name__)


async def run_slack_digest(
    pool: Any,
    *,
    window_hours: float,
    edition_label: str,
    title: str,
    ntfy_topic: str | None,
    source_caps: dict[str, int] | None,
    fetch_articles: Callable[..., Awaitable[list[dict]]],
    generate_digest: Callable[..., Awaitable[Any]],
    publish: Callable[[Any], Path],
    publish_fallback: Callable[[list[dict]], Path],
    notify_failure: Callable[..., None],
) -> dict | None:
    rows = await fetch_articles(
        pool,
        categories=["ai"],
        since_hours=window_hours,
        limit=40,
        source_caps=source_caps,
    )
    articles = [dict(r) for r in rows]
    if not articles:
        log.info(
            "slack digest (%s): no articles in %.2fh window; skipping",
            edition_label, window_hours,
        )
        return None

    degraded = False
    digest = None
    try:
        digest = await generate_digest(
            articles=articles, edition_label=edition_label,
        )
    except GeneratorFailure as err:
        log.error(
            "slack digest (%s): LLM failed, publishing headline fallback: %s",
            edition_label, err,
        )
        degraded = True

    try:
        page = publish_fallback(articles) if degraded else publish(digest)
    except Exception as err:
        notify_failure(
            topic=ntfy_topic, title=title,
            reason=f"Feed publish failed: {err}",
        )
        raise

    if degraded:
        notify_failure(
            topic=ntfy_topic, title=title,
            reason="LLM digest failed; published headlines-only fallback",
        )

    log.info(
        "slack digest (%s): published %s (%d candidates, degraded=%s)",
        edition_label, page, len(articles), degraded,
    )
    return {"degraded": degraded, "article_count": len(articles)}
