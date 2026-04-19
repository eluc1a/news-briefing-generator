import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jina_clone.storage.db import fetch_unsummarized, insert_summary, mark_summarized
from jina_clone.summarizer.prompt import build_system_prompt, build_user_prompt

log = logging.getLogger(__name__)


def _render_markdown(*, headline: str, body: str, included: list[dict], generated_at: datetime) -> str:
    sources = sorted({a["source"] for a in included})
    header = (
        f"---\n"
        f"generated_at: {generated_at.isoformat()}\n"
        f"article_count: {len(included)}\n"
        f"sources: {', '.join(sources)}\n"
        f"---\n\n"
        f"# {headline}\n\n"
    )
    return header + body + "\n"


async def run_summarize(
    pool,
    *,
    source_names: list[str],
    provider,
    summaries_dir: Path,
    category: str,
    per_article_cap: int = 4000,
    token_cap: int = 850_000,
    window_hours: float = 24.0,
) -> dict | None:
    since = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    rows = await fetch_unsummarized(
        pool, source_names=source_names, category=category, since=since,
    )
    if not rows:
        log.info("no unsummarized articles for category=%s; nothing to do", category)
        return None

    articles = [dict(r) for r in rows]
    user_prompt, included = await build_user_prompt(
        articles,
        count_tokens=provider.count_tokens,
        per_article_cap=per_article_cap,
        token_cap=token_cap,
    )

    log.info(
        "summarizing %d articles (category=%s) with %s (%s)",
        len(included), category, provider.name, provider.model,
    )
    # LLM call first — if it raises, nothing is written, no DB mutations occur
    result = await provider.summarize(build_system_prompt(category), user_prompt)

    generated_at = datetime.now()
    summaries_dir.mkdir(parents=True, exist_ok=True)
    path = summaries_dir / f"{generated_at.strftime('%Y-%m-%d-%H%M')}-{category}.md"
    path.write_text(
        _render_markdown(
            headline=result["headline"],
            body=result["body"],
            included=included,
            generated_at=generated_at,
        )
    )

    summary_id = await insert_summary(
        pool,
        category=category,
        headline=result["headline"],
        facts=result["body"],
        article_count=len(included),
    )
    await mark_summarized(pool, links=[a["link"] for a in included])
    log.info("wrote summary %s id=%s", path, summary_id)
    return {"summary_id": summary_id, "output_path": str(path)}
