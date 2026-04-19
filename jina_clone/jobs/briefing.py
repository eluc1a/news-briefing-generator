import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from jina_clone.briefing.config import BriefingCategories
from jina_clone.briefing.generator import GeneratorFailure
from jina_clone.briefing.markdown import briefing_to_markdown
from jina_clone.briefing.schema import Briefing


log = logging.getLogger(__name__)


class NotEnoughArticles(RuntimeError):
    pass


@dataclass
class BriefingResult:
    printed: bool
    emergency_used: bool
    pdf_path: Path
    article_count: int


def _partition_articles(
    rows: list[dict],
    categories: BriefingCategories,
) -> tuple[dict[str, list[dict]], list[dict]]:
    by_panel: dict[str, list[dict]] = {p.key: [] for p in categories.panels}
    briefs_pool: list[dict] = []
    briefs_set = set(categories.briefs_categories)
    for row in rows:
        cat = row["category"]
        panel_key = categories.panel_for_category(cat)
        if panel_key:
            by_panel[panel_key].append(dict(row))
        elif cat in briefs_set:
            briefs_pool.append(dict(row))
        # else: silently drop unknown categories
    return by_panel, briefs_pool


async def run_briefing(
    *,
    pool: Any,
    categories: BriefingCategories,
    briefings_dir: Path,
    print_queue: str,
    ntfy_topic: str | None,
    weather_provider: Callable[[], dict],
    today_label: str,
    volume_label: str,
    generated_at_label: str,
    iso_date: str,
    fetch_articles: Callable[..., Awaitable[list[dict]]],
    generate: Callable[..., Awaitable[Briefing]],
    render: Callable[..., Path],
    print_pdf: Callable[..., str],
    notify_printed: Callable[..., None],
    notify_failure: Callable[..., None],
    insert_summary: Callable[..., Awaitable[int]],
    emergency_path: Path,
) -> BriefingResult:
    """Run the full briefing pipeline. All collaborators injected for testability."""

    rows = await fetch_articles(
        pool,
        categories=categories.all_categories(),
        since_hours=24,
        limit=80,
    )
    log.info("fetched %d articles for briefing", len(rows))

    if len(rows) < categories.min_articles_total:
        reason = (
            f"Too few articles: {len(rows)} < min {categories.min_articles_total}. "
            "Briefing aborted."
        )
        log.warning(reason)
        notify_failure(topic=ntfy_topic, reason=reason)
        raise NotEnoughArticles(reason)

    by_panel, briefs_pool = _partition_articles(rows, categories)
    weather = weather_provider()

    emergency_used = False
    try:
        briefing = await generate(
            articles_by_panel=by_panel,
            briefs_pool=briefs_pool,
            weather=weather,
            today=today_label,
            volume=volume_label,
        )
    except GeneratorFailure as e:
        log.error("generator failed twice — using emergency edition: %s", e)
        notify_failure(
            topic=ntfy_topic,
            reason=f"Generator failed twice; emergency edition printed. {e}",
        )
        briefing = Briefing.model_validate_json(emergency_path.read_text())
        emergency_used = True

    briefings_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = briefings_dir / f"{iso_date}.pdf"
    render(briefing, pdf_path, generated_at=generated_at_label, iso_date=iso_date)
    log.info("rendered %s (%d bytes)", pdf_path, pdf_path.stat().st_size)

    try:
        msg = print_pdf(pdf_path, queue=print_queue)
        log.info("print: %s", msg)
    except Exception as e:
        notify_failure(topic=ntfy_topic, reason=str(e))
        raise

    if not emergency_used:
        notify_printed(topic=ntfy_topic, pages=2)
        try:
            facts_md = briefing_to_markdown(briefing)
            row_id = await insert_summary(
                pool,
                category="briefing",
                headline=briefing.lead.headline,
                facts=facts_md,
                article_count=len(rows),
            )
            log.info("logged briefing %d to news_summaries", row_id)
        except Exception as e:  # do NOT raise — paper already came out
            log.warning("failed to log briefing to news_summaries: %s", e)

    return BriefingResult(
        printed=True,
        emergency_used=emergency_used,
        pdf_path=pdf_path,
        article_count=len(rows),
    )
