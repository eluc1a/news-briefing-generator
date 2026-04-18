import logging
from datetime import datetime
from pathlib import Path

from jina_clone.storage.db import fetch_unsummarized, insert_summary, mark_summarized
from jina_clone.summarizer.prompt import SYSTEM_PROMPT, build_user_prompt

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
    category: str = "ai",
    per_article_cap: int = 4000,
    total_cap: int = 200_000,
) -> dict | None:
    rows = await fetch_unsummarized(pool, source_names=source_names)
    if not rows:
        log.info("no unsummarized articles; nothing to do")
        return None

    articles = [dict(r) for r in rows]
    user_prompt, included = build_user_prompt(
        articles, per_article_cap=per_article_cap, total_cap=total_cap
    )

    log.info("summarizing %d articles with %s (%s)", len(included), provider.name, provider.model)
    # LLM call first — if it raises, nothing is written, no DB mutations occur
    result = await provider.summarize(SYSTEM_PROMPT, user_prompt)

    generated_at = datetime.now()
    summaries_dir.mkdir(parents=True, exist_ok=True)
    path = summaries_dir / generated_at.strftime("%Y-%m-%d-%H%M.md")
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
