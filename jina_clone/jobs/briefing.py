import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from jina_clone.briefing.config import BriefingConfig, SectionDef
from jina_clone.briefing.generator import GeneratorFailure
from jina_clone.briefing.markdown import briefing_to_markdown
from jina_clone.briefing.schema import (
    Brief, Briefing, BRIEFS_COUNT_MIN, EditorDecision, FrontMatter,
    HourlyForecast, MarketsBlock, Panel, PANEL_ALSO_COUNT, WeatherStrip,
)


log = logging.getLogger(__name__)


class NotEnoughArticles(RuntimeError):
    pass


@dataclass
class BriefingResult:
    printed: bool
    emergency_used: bool
    pdf_path: Path
    article_count: int


FetchFn = Callable[..., Awaitable[list[dict]]]
FrontMatterFn = Callable[..., Awaitable[FrontMatter]]
PanelFn = Callable[..., Awaitable[Panel]]
BriefsFn = Callable[..., Awaitable[list[Brief]]]
EditorFn = Callable[..., Awaitable[Any]]
WeatherFn = Callable[[], Awaitable[dict]]
MarketsFn = Callable[[], Awaitable[dict]]


def _dedupe_by_link(articles: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for a in articles:
        link = a.get("link")
        if link and link not in seen:
            seen.add(link)
            out.append(a)
    return out


def _trim_positional(
    panels: list[Panel], briefs: list[Brief],
) -> tuple[list[Panel], list[Brief]]:
    """Fallback trim when there's no editor decision (or it failed):
    keep the first N items positionally rather than by any judgment."""
    trimmed = [
        p.model_copy(update={"also": list(p.also[:PANEL_ALSO_COUNT])})
        for p in panels
    ]
    return trimmed, list(briefs[:BRIEFS_COUNT_MIN])


def _apply_cuts(
    decision: EditorDecision,
    keys: list[str],
    panels: list[Panel],
    briefs: list[Brief],
) -> tuple[list[Panel], list[Brief]]:
    """Remove the editor's named indices from each panel's `also` list
    and from `briefs`. `keys` are the panel section keys in the same
    order as `panels` (zipped to match decision.cuts' `section`)."""
    cut_idx: dict[str, set[int]] = {}
    for c in decision.cuts:
        cut_idx.setdefault(c.section, set()).add(c.index)
    new_panels = [
        p.model_copy(update={"also": [
            it for i, it in enumerate(p.also)
            if i not in cut_idx.get(key, set())
        ]})
        for key, p in zip(keys, panels)
    ]
    new_briefs = [
        b for i, b in enumerate(briefs)
        if i not in cut_idx.get("briefs", set())
    ]
    return new_panels, new_briefs


async def assemble_briefing(
    *,
    pool: Any,
    config: BriefingConfig,
    window_hours: float,
    title: str,
    weather_provider: WeatherFn,
    markets_provider: MarketsFn,
    today_label: str,
    volume_label: str,
    iso_date: str,
    fetch_articles: FetchFn,
    generate_front_matter: FrontMatterFn,
    generate_panel: PanelFn,
    generate_briefs: BriefsFn,
    generate_editor: EditorFn | None = None,
) -> tuple[Briefing, int]:
    """Fetch → front-matter → panels+briefs → editor dedup → assemble.

    Pure core shared by `run_briefing` (production, adds emergency
    fallback + render + print + log) and the `briefing generate`
    CLI subcommand (debug, just writes JSON). Returns the fully
    assembled `Briefing` and the total article count used.

    Raises
    ------
    NotEnoughArticles
        Total fetched articles across all sections + briefs is below
        `config.min_articles_total`.
    GeneratorFailure
        Any of the seven Gemini calls returned invalid output twice.
    """

    # --- Step 1: fan-out fetches (4 sections + briefs) ---
    section_pools: dict[str, list[dict]] = {}

    async def _fetch_section(section: SectionDef) -> tuple[str, list[dict]]:
        rows = await fetch_articles(
            pool,
            categories=list(section.categories),
            per_source_cap=config.per_source_cap,
            limit=section.limit,
            since_hours=window_hours,
            source_caps=dict(config.source_caps),
        )
        return section.key, [dict(r) for r in rows]

    async def _fetch_briefs() -> list[dict]:
        rows = await fetch_articles(
            pool,
            categories=list(config.briefs.categories),
            per_source_cap=config.per_source_cap,
            limit=config.briefs.limit,
            since_hours=window_hours,
            source_caps=dict(config.source_caps),
        )
        return [dict(r) for r in rows]

    section_results, briefs_pool = await asyncio.gather(
        asyncio.gather(*[_fetch_section(s) for s in config.sections]),
        _fetch_briefs(),
    )
    for key, rows in section_results:
        section_pools[key] = rows

    total = sum(len(p) for p in section_pools.values()) + len(briefs_pool)
    log.info(
        "fetched %d articles across %d sections + briefs",
        total, len(config.sections),
    )

    if total < config.min_articles_total:
        raise NotEnoughArticles(
            f"Too few articles: {total} < min {config.min_articles_total}. "
            "Briefing aborted."
        )

    weather = await weather_provider()
    hourly = HourlyForecast.model_validate(weather.pop("hourly"))
    markets = MarketsBlock.model_validate(await markets_provider())

    # --- Step 2: front matter (serial, so panels can exclude its URL) ---
    front_pool = _dedupe_by_link([
        a
        for s in config.sections
        for a in section_pools[s.key][: config.front_matter_top_per_section]
    ])
    front = await generate_front_matter(
        articles=front_pool,
        weather=weather,
        today=today_label,
        volume=volume_label,
        title=title,
    )
    exclude = {front.lead_source_url}

    # --- Step 3: panels + briefs (parallel) ---
    panel_coros = [
        generate_panel(
            section=s,
            articles=section_pools[s.key],
            exclude_urls=exclude,
            title=title,
            avoid_headlines=[front.lead.headline],
        )
        for s in config.sections
    ]
    briefs_coro = generate_briefs(
        articles=briefs_pool,
        exclude_urls=exclude,
        title=title,
        avoid_headlines=[front.lead.headline],
    )

    panels_and_briefs = await asyncio.gather(*panel_coros, briefs_coro)
    panels: list[Panel] = list(panels_and_briefs[:-1])
    briefs: list[Brief] = panels_and_briefs[-1]

    # --- Step 3.5: editor-in-chief dedup (spec 2026-07-20) ---
    keys = [s.key for s in config.sections]
    if generate_editor is not None:
        try:
            decision = await generate_editor(
                lead_headline=front.lead.headline,
                panels=list(zip(keys, panels)),
                briefs=briefs,
                title=title,
            )
            panels, briefs = _apply_cuts(decision, keys, panels, briefs)
            # One targeted rerun round for panel ledes duplicating the
            # lead (or each other). Rerun failure keeps the original —
            # a duplicate lede beats a missing panel.
            for dupe in decision.lede_dupes:
                idx = keys.index(dupe.section)
                old = panels[idx]
                old_url = old.lede_sources[0].url if old.lede_sources else None
                log.info("lede dupe in %s (%s) — rerunning panel",
                         dupe.section, dupe.duplicate_of)
                try:
                    fresh = await generate_panel(
                        section=config.sections[idx],
                        articles=section_pools[dupe.section],
                        exclude_urls=exclude | ({old_url} if old_url else set()),
                        title=title,
                        avoid_headlines=[front.lead.headline,
                                         old.lede_headline],
                    )
                    panels[idx] = fresh
                except GeneratorFailure as e:
                    log.warning("panel rerun failed for %s — keeping "
                                "original: %s", dupe.section, e)
        except GeneratorFailure as e:
            log.warning("editor call failed — positional trim: %s", e)
    # All paths land on exact published counts; no-op when the editor
    # already cut to size.
    panels, briefs = _trim_positional(panels, briefs)

    briefing = Briefing(
        title=title,
        date=today_label,
        volume=volume_label,
        weather=WeatherStrip(**weather),
        hourly=hourly,
        markets=markets,
        lead=front.lead,
        panels=panels,
        pull_quote=front.pull_quote,
        briefs=briefs,
        data_point=front.data_point,
        on_this_day=front.on_this_day,
    )
    return briefing, total


async def run_briefing(
    *,
    pool: Any,
    config: BriefingConfig,
    window_hours: float,
    title: str,
    pdf_path: Path,
    print_queue: str,
    ntfy_topic: str | None,
    weather_provider: WeatherFn,
    markets_provider: MarketsFn,
    today_label: str,
    volume_label: str,
    generated_at_label: str,
    iso_date: str,
    fetch_articles: FetchFn,
    generate_front_matter: FrontMatterFn,
    generate_panel: PanelFn,
    generate_briefs: BriefsFn,
    generate_editor: EditorFn | None = None,
    render: Callable[..., Path],
    print_pdf: Callable[..., str],
    notify_printed: Callable[..., None],
    notify_failure: Callable[..., None],
    insert_summary: Callable[..., Awaitable[int]],
    emergency_path: Path,
    print_enabled: bool = True,
) -> BriefingResult:
    """Full pipeline: assemble → render → print → log, with
    NotEnoughArticles and emergency-edition fallback around assemble.

    When ``print_enabled`` is False, the PDF is still rendered and (via the
    injected ``render`` wrapper) published online, but it is not submitted to
    the CUPS queue — the off switch for pausing physical copies."""

    emergency_used = False
    try:
        briefing, total = await assemble_briefing(
            pool=pool,
            config=config,
            window_hours=window_hours,
            title=title,
            weather_provider=weather_provider,
            markets_provider=markets_provider,
            today_label=today_label,
            volume_label=volume_label,
            iso_date=iso_date,
            fetch_articles=fetch_articles,
            generate_front_matter=generate_front_matter,
            generate_panel=generate_panel,
            generate_briefs=generate_briefs,
            generate_editor=generate_editor,
        )
    except NotEnoughArticles as e:
        log.warning(str(e))
        notify_failure(topic=ntfy_topic, title=title, reason=str(e))
        raise
    except GeneratorFailure as e:
        log.error("generator failed — using emergency edition: %s", e)
        notify_failure(
            topic=ntfy_topic,
            title=title,
            reason=f"Generator failed; emergency edition printed. {e}",
        )
        briefing = Briefing.model_validate_json(emergency_path.read_text())
        briefing = briefing.model_copy(update={"title": title})
        emergency_used = True
        total = 0

    # --- Step 4: render + print ---
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    render(briefing, pdf_path, generated_at=generated_at_label, iso_date=iso_date)
    log.info("rendered %s (%d bytes)", pdf_path, pdf_path.stat().st_size)

    if print_enabled:
        try:
            msg = print_pdf(pdf_path, queue=print_queue)
            log.info("print: %s", msg)
        except Exception as e:
            notify_failure(topic=ntfy_topic, title=title, reason=str(e))
            raise
    else:
        # Physical printing paused (2026-06-21): briefing is still generated,
        # rendered, and published online — we just skip the CUPS queue.
        log.info("print: SKIPPED (print_enabled=False) — %s rendered, not queued", pdf_path)

    if not emergency_used:
        notify_printed(topic=ntfy_topic, title=title, pages=2)
        try:
            facts_md = briefing_to_markdown(briefing)
            row_id = await insert_summary(
                pool,
                category="briefing",
                headline=briefing.lead.headline,
                facts=facts_md,
                article_count=total,
            )
            log.info("logged briefing %d to news_summaries", row_id)
        except Exception as e:  # do NOT raise — paper is already out
            log.warning("failed to log briefing to news_summaries: %s", e)

    return BriefingResult(
        printed=True,
        emergency_used=emergency_used,
        pdf_path=pdf_path,
        article_count=total,
    )
