import asyncio
import json
import logging
import os
import re
from typing import Awaitable, Callable, TypeVar

from anthropic import AsyncAnthropic
from pydantic import BaseModel, Field, ValidationError

from jina_clone.briefing.config import SectionDef
from jina_clone.briefing.schema import (
    Brief, BRIEFS_COUNT_MAX, BRIEFS_COUNT_MIN, FrontMatter, Panel,
)


MODEL = os.environ.get("LLM_MODEL", "claude-sonnet-4-6")
MAX_TOKENS = 4096
PER_ARTICLE_BODY_CAP = 3000

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
_log = logging.getLogger(__name__)

# Per-run usage accumulator. Not thread-safe — relies on briefing runs being
# serial, which they are (one cron firing at a time).
_USAGE: list[dict] = []

BRIEFING_LLM_BACKEND = os.environ.get("BRIEFING_LLM_BACKEND", "cli")
CLI_TIMEOUT = float(os.environ.get("BRIEFING_CLI_TIMEOUT", "120"))
CLI_CONCURRENCY = int(os.environ.get("BRIEFING_CLI_CONCURRENCY", "3"))
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
_CLI_SEMAPHORE = asyncio.Semaphore(CLI_CONCURRENCY)


def reset_usage() -> None:
    _USAGE.clear()


def pop_usage_totals() -> dict:
    totals = {
        "calls": len(_USAGE),
        "input": sum(u["input"] for u in _USAGE),
        "output": sum(u["output"] for u in _USAGE),
        "cache_read": sum(u["cache_read"] for u in _USAGE),
        "cache_creation": sum(u["cache_creation"] for u in _USAGE),
        "cost": sum(u.get("cost", 0.0) for u in _USAGE),
    }
    _USAGE.clear()
    return totals


class GeneratorFailure(RuntimeError):
    """Raised when an LLM call returns invalid JSON twice in a row."""


CallLLM = Callable[[object, str], Awaitable[str]]

T = TypeVar("T")


# ==================================================================
# Shared prompt fragments
# ==================================================================

VOICE_RULES = """VOICE RULES — STRICT:
- Facts only. Report what happened, who acted, numbers, dates.
- No opinions. No editorial framing. No "experts say", "analysts argue",
  "this could mean", "raises questions about", "underscores the need for",
  "marks a turning point". If a source quotes an analyst's opinion and you
  must mention it, attribute it ("X said ..."); do not adopt it as your own.
- No hype, no rhetorical questions, no scene-setting, no metaphor.
- Specific. Numbers, names, places, dates, percentages, dollar amounts.
- Tight prose, not telegraphic. Full sentences, no headlines-as-sentences."""


CONSEQUENCE_RULE = """CONSEQUENCE RULE:
Prefer stories with material impact on policy, economy, public safety,
national security, infrastructure, or civil rights. Deprioritize celebrity
deaths, sports scores, local curiosities, tabloid oddities, entertainment
gossip, and ceremonial events unless they carry demonstrable broader
consequence."""


LENGTH_RULE = """LENGTH RULE — STRICT:
- Every word cap in the STRUCTURE section below is a HARD LIMIT, not a
  suggestion. Stay within the range.
- Prefer the LOW end of each range. A 22-word item that lands at 16
  words is better than one that lands at 21.
- If a sentence can be cut without losing a fact, cut it. Filler words
  ("notably", "importantly", "reportedly") go first.
- No hedges, no scene-setting, no restating context already in the
  lede. One sentence per `also` item. Period."""


# ==================================================================
# Section-specific scope rules
# ==================================================================

SECTION_SCOPE_RULES: dict[str, str] = {
    "national": (
        "SCOPE: National panel. Only stories with direct US impact. A "
        "foreign event qualifies only if it has named US actors, US policy "
        "implications, or US economic exposure. Drop anything else — do not "
        "invent a US angle."
    ),
    "economy": (
        "SCOPE: Economy & Markets panel. Markets, earnings, macroeconomic "
        "indicators, central bank action, major corporate moves. Skip sports "
        "and entertainment. Non-US stories allowed when they affect global "
        "markets."
    ),
    "ai": (
        "SCOPE: AI & Technology panel. Artificial intelligence and machine "
        "learning only. Model releases, AI research papers, AI company news, "
        "AI policy, AI infrastructure. Skip generic consumer tech, generic "
        "hardware, or scientific research unrelated to AI."
    ),
    "international": (
        "SCOPE: International panel. World news excluding the United States "
        "(covered in the National panel). Prefer variety across regions — if "
        "two articles are from the same country, include at most one unless "
        "both are top-tier consequential."
    ),
}


# ==================================================================
# Full system prompts (one per call type)
# ==================================================================

PANEL_STRUCTURE_RULES = """STRUCTURE — every field required:
- section: exactly the section title passed in the prompt.
- lede_headline: ≤ 14 words, factual, the strongest single story for this
  section.
- lede_body: 45-60 words on that story. Facts only. NEVER exceed 60 words.
- also: EXACTLY 4 PanelItem entries, each a distinct event from this
  section's scope. Every item has:
    - headline: ≤ 8 words, concrete subject + action.
    - body: 15-22 words, facts only (date, numbers, named actors,
      percentages). Separate EVERY distinct fact with " · " (one space,
      a Unicode middle dot U+00B7, one space) — no cap on how many
      separators a body may have.

      EACH ` · `-SEPARATED UNIT MUST BE A GRAMMATICALLY COMPLETE SENTENCE
      OR A CLEAN STANDALONE PHRASE. Read each unit aloud in isolation —
      if it reads as broken English, rewrite. Specifically:
        * After a reporting verb (`said`, `reported`, `confirmed`,
          `announced`, `noted`, `stated`) followed by a date/time, you
          MUST insert ` · ` BEFORE the object clause. Never elide the
          word "that" by gluing the object clause directly onto
          "<verb> <date>".
        * Never glue facts together with "and", "after", participial
          phrases (e.g. ", determining X"), or relative clauses
          (e.g. "...he argued would...").
        * A noun phrase used as a standalone fact is fine
          ("12,400 acres burned", "no fatalities") — but only if it
          reads cleanly on its own.

      NEVER exceed 22 words.

      Examples:
        GOOD (3 facts, each standalone): "Cal Fire reports 78% containment of the Vista Lake fire · 12,400 acres burned · no fatalities"
        GOOD (3 facts, reporting verb correctly broken): "U.S. Southern Command reported Sunday · a strike on a drug vessel killed 3 · 186 dead since September"
        BAD (`reported Sunday` glued to object clause): "U.S. Southern Command reported Sunday a strike on a drug vessel killed 3"
        BAD (run-on via "after"): "Africa Corps withdrew from Kidal after Tuareg rebels attacked across Mali"
        BAD (run-on via dropped "that" + relative clause): "AA closed the door on merger talks he argued would have created jobs"
Never fabricate. If fewer than 4 distinct stories exist in the input,
repeat the strongest adjacent items but do NOT invent facts."""


FRONT_MATTER_STRUCTURE_RULES = """STRUCTURE — every field required:
- lead: the single most consequential factual story of the day drawn from
  the input articles.
    - headline: ≤ 14 words, factual.
    - deck: one sentence, ≤ 25 words, sets up the body.
    - body: 110-160 words. Plain prose. Cover who/what/when/where/how-much.
      NEVER exceed 160 words.
    - at_a_glance: exactly 3 short factual bullets about the lead, each
      ≤ 10 words.
- lead_source_url: EXACTLY the `link` value of the input article the lead
  is based on. Must match one of the input URLs verbatim. This field is
  critical — if you hallucinate a URL the briefing will be rejected.
- pull_quote: a verbatim sentence from one of the input articles, with
  attribution embedded ("..." — Name, Outlet). Never invent a quote.
  ≤ 35 words total.
- data_point: `value` is a real attributable figure with units (e.g.
  "$220 million"); `context` is 25-35 words explaining what it counts and
  where it comes from. Cite the source organisation. NEVER exceed 35 words.
- on_this_day: a verifiable historical event on today's date. `body` is
  35-50 words, facts only. NEVER exceed 50 words. If unsure of the exact
  date, pick a well-known event from the week and say so in the title."""


BRIEFS_STRUCTURE_RULES = """STRUCTURE:
Output {"briefs": [...]} containing EXACTLY 6 Brief entries. Each entry:
  - topic: 1-3 word category label ("Cybersecurity", "Markets", "Linux",
    "Investigations").
  - body: 22-30 words, facts only. NEVER exceed 30 words.
Each brief covers a distinct story. Consequence beats curiosity."""


def _panel_system_prompt(section: SectionDef, title: str) -> str:
    scope = SECTION_SCOPE_RULES[section.key]
    return f"""You are a section editor of "{title}" daily briefing.
Your task: produce the JSON for the "{section.title}" panel only.

{scope}

{VOICE_RULES}

{CONSEQUENCE_RULE}

{LENGTH_RULE}

{PANEL_STRUCTURE_RULES}

Output: valid JSON matching the Panel schema below. No preamble. No
markdown fence. The `section` field must be exactly "{section.title}".
"""


def _front_matter_system_prompt(title: str) -> str:
    return f"""You are the editor of "{title}" daily
briefing. Your task: produce the front-matter JSON (lead, pull_quote,
data_point, on_this_day) given input articles across all sections.

{VOICE_RULES}

{CONSEQUENCE_RULE}

{LENGTH_RULE}

{FRONT_MATTER_STRUCTURE_RULES}

Output: valid JSON matching the FrontMatter schema below. No preamble. No
markdown fence.
"""


def _briefs_system_prompt(title: str) -> str:
    return f"""You are a section editor of "{title}"
daily briefing. Your task: produce the "briefs" rundown — a list of short
factual items from the supplementary pool.

{VOICE_RULES}

{CONSEQUENCE_RULE}

{LENGTH_RULE}

{BRIEFS_STRUCTURE_RULES}

Output: valid JSON matching the schema below. No preamble. No markdown
fence.
"""


# ==================================================================
# User-message builders
# ==================================================================

def _format_article(art: dict, body_cap: int = PER_ARTICLE_BODY_CAP) -> str:
    body = (art.get("content") or "")[:body_cap]
    return (
        f"Source: {art.get('source', '?')}\n"
        f"Title: {art.get('title', '?')}\n"
        f"Link: {art.get('link', '?')}\n\n"
        f"{body}"
    )


def _filter_excluded(articles: list[dict], exclude_urls: set[str]) -> list[dict]:
    if not exclude_urls:
        return articles
    return [a for a in articles if a.get("link") not in exclude_urls]


def _build_front_matter_user_msg(
    *, articles: list[dict], weather: dict, today: str, volume: str,
) -> str:
    parts = [
        f"Today: {today}",
        f"Volume: {volume}",
        f"Weather: {json.dumps(weather)}",
        "",
        f"--- Candidate lead articles ({len(articles)}) ---",
    ]
    for art in articles:
        parts.append("")
        parts.append(_format_article(art))
    parts.append("")
    parts.append("--- Schema ---")
    parts.append(json.dumps(FrontMatter.model_json_schema(), indent=2))
    parts.append("")
    parts.append("Emit the FrontMatter JSON now.")
    return "\n".join(parts)


def _build_panel_user_msg(
    *, section: SectionDef, articles: list[dict],
) -> str:
    parts = [
        f"Panel: {section.title} ({len(articles)} articles)",
    ]
    for art in articles:
        parts.append("")
        parts.append(_format_article(art))
    parts.append("")
    parts.append("--- Schema ---")
    parts.append(json.dumps(Panel.model_json_schema(), indent=2))
    parts.append("")
    parts.append(f"Emit the Panel JSON for \"{section.title}\" now.")
    return "\n".join(parts)


class _BriefsResponse(BaseModel):
    briefs: list[Brief] = Field(
        min_length=BRIEFS_COUNT_MIN, max_length=BRIEFS_COUNT_MAX,
    )


def _build_briefs_user_msg(*, articles: list[dict]) -> str:
    parts = [f"Briefs pool ({len(articles)} articles)"]
    for art in articles:
        parts.append("")
        parts.append(_format_article(art, body_cap=1500))
    parts.append("")
    parts.append("--- Schema ---")
    parts.append(json.dumps(_BriefsResponse.model_json_schema(), indent=2))
    parts.append("")
    parts.append("Emit the JSON now.")
    return "\n".join(parts)


# ==================================================================
# Real Anthropic call
# ==================================================================

async def _real_call_llm(
    client: AsyncAnthropic, prompt: str, *, system: str,
) -> str:
    response = await client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=[
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": prompt}],
    )
    u = response.usage
    entry = {
        "input": u.input_tokens,
        "output": u.output_tokens,
        "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
        "cache_creation": getattr(u, "cache_creation_input_tokens", 0) or 0,
    }
    _USAGE.append(entry)
    _log.info(
        "briefing claude call: input=%d output=%d cache_read=%d cache_creation=%d",
        entry["input"], entry["output"], entry["cache_read"], entry["cache_creation"],
    )
    text = "".join(
        block.text for block in response.content if block.type == "text"
    )
    return _FENCE.sub("", text).strip()


async def _cli_call_llm(prompt: str, *, system: str, model: str) -> str:
    """Generate via the Claude Code CLI in print mode (subscription auth).

    Strips ANTHROPIC_API_KEY from the child env so `claude` uses the
    logged-in subscription rather than billing the API.
    """
    argv = [
        CLAUDE_BIN, "-p",
        "--output-format", "json",
        "--model", model,
        "--system-prompt", system,
        "--tools", "",
        "--permission-mode", "dontAsk",
        "--no-session-persistence",
    ]
    env = {**os.environ}
    env.pop("ANTHROPIC_API_KEY", None)
    npm_bin = os.path.expanduser("~/.npm-global/bin")
    if npm_bin not in env.get("PATH", "").split(":"):
        env["PATH"] = npm_bin + ":" + env.get("PATH", "")

    async with _CLI_SEMAPHORE:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=prompt.encode()), timeout=CLI_TIMEOUT
            )
        except asyncio.TimeoutError as e:
            proc.kill()
            await proc.wait()
            raise GeneratorFailure(
                f"claude -p timed out after {CLI_TIMEOUT}s"
            ) from e

    if proc.returncode != 0:
        raise GeneratorFailure(
            f"claude -p exited {proc.returncode}: "
            f"{stderr.decode(errors='replace').strip()}"
        )
    try:
        envelope = json.loads(stdout.decode())
    except json.JSONDecodeError as e:
        raise GeneratorFailure(
            f"claude -p returned non-JSON: {stdout[:200]!r}"
        ) from e
    if envelope.get("is_error"):
        raise GeneratorFailure(
            f"claude -p error: {str(envelope.get('result', ''))[:300]}"
        )

    u = envelope.get("usage") or {}
    entry = {
        "input": u.get("input_tokens", 0) or 0,
        "output": u.get("output_tokens", 0) or 0,
        "cache_read": u.get("cache_read_input_tokens", 0) or 0,
        "cache_creation": u.get("cache_creation_input_tokens", 0) or 0,
        "cost": envelope.get("total_cost_usd", 0.0) or 0.0,
    }
    _USAGE.append(entry)
    _log.info(
        "briefing claude -p call: input=%d output=%d cost=%.4f",
        entry["input"], entry["output"], entry["cost"],
    )
    text = envelope.get("result", "")
    return _FENCE.sub("", text).strip()


def _ensure_client(client: AsyncAnthropic | None) -> AsyncAnthropic:
    if client is None:
        return AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return client


def _build_default_call_llm(system_prompt: str, client: object) -> CallLLM:
    """Return the default call_llm for the configured backend.

    cli  -> claude -p subprocess (subscription auth), no API client needed.
    api  -> Anthropic API via _real_call_llm (fallback / tests).
    """
    if BRIEFING_LLM_BACKEND == "cli":
        async def _cli_wrapper(cl: object, prompt: str) -> str:
            return await _cli_call_llm(prompt, system=system_prompt, model=MODEL)
        return _cli_wrapper

    api_client = _ensure_client(client)

    async def _api_wrapper(cl: object, prompt: str) -> str:
        return await _real_call_llm(api_client, prompt, system=system_prompt)
    return _api_wrapper


# Two-try retry loop. The ``parse`` callable raises ValidationError
# (or GeneratorFailure with a string-able message) on failure; we append
# the error text to the prompt and retry exactly once.
async def _call_with_retry(
    *,
    call_llm: CallLLM,
    client: object,
    user_msg: str,
    parse: Callable[[str], T],
) -> T:
    # Wrap call_llm to carry system_prompt if the caller wants it.
    # Fakes used in tests accept (client, prompt) and ignore system.
    raw = await call_llm(client, user_msg)
    try:
        return parse(raw)
    except (ValidationError, GeneratorFailure, ValueError) as first_err:
        retry_msg = (
            user_msg + f"\n\nPrevious attempt failed validation:\n{first_err}\n"
            "Fix and re-emit valid JSON only."
        )
        raw2 = await call_llm(client, retry_msg)
        try:
            return parse(raw2)
        except (ValidationError, GeneratorFailure, ValueError) as second_err:
            raise GeneratorFailure(
                f"LLM returned invalid JSON twice. "
                f"First: {first_err}; second: {second_err}"
            ) from second_err


# ==================================================================
# Public functions
# ==================================================================

async def generate_front_matter(
    *,
    articles: list[dict],
    weather: dict,
    today: str,
    volume: str,
    title: str,
    call_llm: CallLLM | None = None,
    client: AsyncAnthropic | None = None,
) -> FrontMatter:
    system_prompt = _front_matter_system_prompt(title)
    if call_llm is None:
        call_llm = _build_default_call_llm(system_prompt, client)

    user_msg = _build_front_matter_user_msg(
        articles=articles, weather=weather, today=today, volume=volume,
    )
    valid_urls = {a.get("link") for a in articles}

    def parse(raw: str) -> FrontMatter:
        fm = FrontMatter.model_validate_json(raw)
        if fm.lead_source_url not in valid_urls:
            raise ValueError(
                f"lead_source_url {fm.lead_source_url!r} not in input article links"
            )
        return fm

    return await _call_with_retry(
        call_llm=call_llm, client=client,
        user_msg=user_msg,
        parse=parse,
    )


async def generate_panel(
    *,
    section: SectionDef,
    articles: list[dict],
    exclude_urls: set[str],
    title: str,
    call_llm: CallLLM | None = None,
    client: AsyncAnthropic | None = None,
) -> Panel:
    system_prompt = _panel_system_prompt(section, title)
    if call_llm is None:
        call_llm = _build_default_call_llm(system_prompt, client)

    filtered = _filter_excluded(articles, exclude_urls)
    user_msg = _build_panel_user_msg(section=section, articles=filtered)
    return await _call_with_retry(
        call_llm=call_llm, client=client,
        user_msg=user_msg,
        parse=Panel.model_validate_json,
    )


async def generate_briefs(
    *,
    articles: list[dict],
    exclude_urls: set[str],
    title: str,
    call_llm: CallLLM | None = None,
    client: AsyncAnthropic | None = None,
) -> list[Brief]:
    system_prompt = _briefs_system_prompt(title)
    if call_llm is None:
        call_llm = _build_default_call_llm(system_prompt, client)

    filtered = _filter_excluded(articles, exclude_urls)
    user_msg = _build_briefs_user_msg(articles=filtered)

    def parse(raw: str) -> list[Brief]:
        return _BriefsResponse.model_validate_json(raw).briefs

    return await _call_with_retry(
        call_llm=call_llm, client=client,
        user_msg=user_msg,
        parse=parse,
    )
