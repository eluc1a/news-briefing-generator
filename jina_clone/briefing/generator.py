import json
import os
from typing import Awaitable, Callable, TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel, Field, ValidationError

from jina_clone.briefing.config import SectionDef
from jina_clone.briefing.schema import (
    Brief, FrontMatter, Panel,
)


MODEL = "gemini-3.1-flash-lite-preview"
PER_ARTICLE_BODY_CAP = 3000


class GeneratorFailure(RuntimeError):
    """Raised when a Gemini call returns invalid JSON twice in a row."""


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
- lede_body: 60-90 words on that story. Facts only.
- also: 3-4 PanelItem entries, each a distinct event from this section's
  scope. Every item has:
    - headline: ≤ 8 words, concrete subject + action.
    - body: 20-30 words, 1-2 sentences, facts only (date, numbers, named
      actors, percentages). No filler.
Never fabricate. If fewer than 3 distinct stories exist in the input,
repeat the strongest adjacent items but do NOT invent facts."""


FRONT_MATTER_STRUCTURE_RULES = """STRUCTURE — every field required:
- lead: the single most consequential factual story of the day drawn from
  the input articles.
    - headline: ≤ 14 words, factual.
    - deck: one sentence, ≤ 30 words, sets up the body.
    - body: 150-250 words. Plain prose. Cover who/what/when/where/how-much.
    - at_a_glance: 3-4 short factual bullets about the lead, each ≤ 12
      words.
- lead_source_url: EXACTLY the `link` value of the input article the lead
  is based on. Must match one of the input URLs verbatim. This field is
  critical — if you hallucinate a URL the briefing will be rejected.
- pull_quote: a verbatim sentence from one of the input articles, with
  attribution embedded ("..." — Name, Outlet). Never invent a quote.
- data_point: `value` is a real attributable figure with units (e.g.
  "$220 million"); `context` is 35-55 words explaining what it counts and
  where it comes from. Cite the source organisation.
- on_this_day: a verifiable historical event on today's date. `body` is
  50-70 words, facts only. If unsure of the exact date, pick a well-known
  event from the week and say so in the title."""


BRIEFS_STRUCTURE_RULES = """STRUCTURE:
Output {"briefs": [...]} containing 5-7 Brief entries. Each entry:
  - topic: 1-3 word category label ("Cybersecurity", "Markets", "Linux",
    "Investigations").
  - body: 30-45 words, facts only.
Each brief covers a distinct story. Consequence beats curiosity."""


def _panel_system_prompt(section: SectionDef, title: str) -> str:
    scope = SECTION_SCOPE_RULES[section.key]
    return f"""You are a section editor of "{title}" daily briefing.
Your task: produce the JSON for the "{section.title}" panel only.

{scope}

{VOICE_RULES}

{CONSEQUENCE_RULE}

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
    briefs: list[Brief] = Field(min_length=5, max_length=7)


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
# Real Gemini call
# ==================================================================

async def _real_call_llm(
    client: genai.Client, prompt: str, *, system: str,
) -> str:
    response = await client.aio.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
        ),
    )
    return (response.text or "").strip()


def _ensure_client(client: genai.Client | None) -> genai.Client:
    if client is None:
        return genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return client


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
    client: genai.Client | None = None,
) -> FrontMatter:
    system_prompt = _front_matter_system_prompt(title)
    if call_llm is None:
        client = _ensure_client(client)
        async def call_llm_wrapper(cl: object, prompt: str) -> str:
            return await _real_call_llm(cl, prompt, system=system_prompt)
        call_llm = call_llm_wrapper

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
    client: genai.Client | None = None,
) -> Panel:
    system_prompt = _panel_system_prompt(section, title)
    if call_llm is None:
        client = _ensure_client(client)
        async def call_llm_wrapper(cl: object, prompt: str) -> str:
            return await _real_call_llm(cl, prompt, system=system_prompt)
        call_llm = call_llm_wrapper

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
    client: genai.Client | None = None,
) -> list[Brief]:
    system_prompt = _briefs_system_prompt(title)
    if call_llm is None:
        client = _ensure_client(client)
        async def call_llm_wrapper(cl: object, prompt: str) -> str:
            return await _real_call_llm(cl, prompt, system=system_prompt)
        call_llm = call_llm_wrapper

    filtered = _filter_excluded(articles, exclude_urls)
    user_msg = _build_briefs_user_msg(articles=filtered)

    def parse(raw: str) -> list[Brief]:
        return _BriefsResponse.model_validate_json(raw).briefs

    return await _call_with_retry(
        call_llm=call_llm, client=client,
        user_msg=user_msg,
        parse=parse,
    )
