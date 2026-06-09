"""Slack digest job: fetch AI articles → LLM digest → webhook post.

Failure policy (2026-06-09 spec):
- LLM failure → post headlines-only fallback, then ntfy (degraded, not
  silent — the channel still gets links).
- Webhook failure → ntfy, then re-raise so the cron log records it.
- Zero articles in window → no post, no ntfy (quiet windows are normal).
"""
import logging
from typing import Any, Awaitable, Callable

from jina_clone.briefing.generator import GeneratorFailure

log = logging.getLogger(__name__)


async def run_slack_digest(
    pool: Any,
    *,
    webhook_url: str,
    window_hours: float,
    edition_label: str,
    date_label: str,
    title: str,
    ntfy_topic: str | None,
    source_caps: dict[str, int] | None,
    fetch_articles: Callable[..., Awaitable[list]],
    generate_digest: Callable[..., Awaitable[Any]],
    format_digest: Callable[..., dict],
    format_fallback: Callable[..., dict],
    post: Callable[[str, dict], None],
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
    try:
        digest = await generate_digest(
            articles=articles, edition_label=edition_label,
        )
        payload = format_digest(
            digest, edition_label=edition_label, date_label=date_label,
        )
    except GeneratorFailure as err:
        log.error(
            "slack digest (%s): LLM failed, posting headline fallback: %s",
            edition_label, err,
        )
        degraded = True
        payload = format_fallback(
            articles, edition_label=edition_label, date_label=date_label,
        )

    try:
        post(webhook_url, payload)
    except Exception as err:
        notify_failure(
            topic=ntfy_topic, title=title,
            reason=f"Slack webhook post failed: {err}",
        )
        raise

    if degraded:
        notify_failure(
            topic=ntfy_topic, title=title,
            reason="LLM digest failed; posted headlines-only fallback",
        )

    log.info(
        "slack digest (%s): posted (%d candidates, degraded=%s)",
        edition_label, len(articles), degraded,
    )
    return {"degraded": degraded, "article_count": len(articles)}
