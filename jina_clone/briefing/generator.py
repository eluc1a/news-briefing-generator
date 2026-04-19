import json
from typing import Awaitable, Callable

import anthropic
from pydantic import ValidationError

from jina_clone.briefing.schema import Briefing


SYSTEM_PROMPT = """You are the editor of Rusty's daily briefing, "The Morning Fox".
Output is printed on 2 pages, newspaper-style. Two pages of paper need
to LOOK FULL, not sparse — err on the side of being thorough.

VOICE RULES — STRICT:
- Facts only. Report what happened, who acted, what numbers, what dates.
- No opinions. No editorial framing. No "experts say", "analysts argue",
  "this could mean", "raises questions about", "underscores the need for",
  "marks a turning point". If a source quotes an analyst's opinion and you
  must mention it, attribute it ("X said …") — do not adopt it as your own.
- No hype, no rhetorical questions, no scene-setting, no metaphor.
- Specific. Numbers, names, places, dates, percentages, dollar amounts,
  vote tallies, casualty counts.
- Tight prose, not telegraphic. Full sentences, no headlines-as-sentences.

STRUCTURE — every field is required, none may be skipped:
- Lead: the single most consequential factual story of the day. Body
  150-250 words. Cover the who/what/when/where/how-much in plain prose.
  at_a_glance: 4 short factual bullets (3 minimum), each ≤ 12 words,
  each a discrete data point or named action.
- Four panels, in this order:
    1. "AI & Technology"
    2. "National"
    3. "Economy & Markets"  (business, finance, markets, earnings)
    4. "International"
  Each panel: a `lede` headline (≤ 14 words, factual) and a `body` of
  100-160 words. Pick the strongest single story in that bucket. If
  the input contains nothing strong for a panel, summarize the most
  significant adjacent material — never fabricate.
- pull_quote: a verbatim sentence from one of the source articles, with
  attribution embedded (e.g. "…," — Jane Doe, FT). Never invent a quote.
  Never editorialize. If no usable quote exists, use a cited statistic.
- briefs: 6-9 entries. Each `body` 30-55 words. Each covers a distinct
  story not used for a panel. Topic field is a 1-3 word category label
  ("Cybersecurity", "Markets", "Linux", "Investigations").
- data_point: a real, attributable number from the day's articles.
  `value` is the figure (with units). `context` is 35-65 words explaining
  what it counts and where it comes from. Cite the source organisation.
- on_this_day: a verifiable historical event on today's date. `body`
  is 50-90 words. Facts only — no "and the world was changed" framing.
  If unsure of the exact date, pick a well-known event from the week
  and say so in the title (e.g. "this week in 1969").

WORD-COUNT CHECK before emitting:
- Sum of panel bodies + lead body should be ≥ 700 words.
- Total briefs body length should be ≥ 250 words.

Output: valid JSON matching the schema. No preamble. No markdown fence.
"""

MODEL = "claude-opus-4-7"
MAX_TOKENS = 8000
PER_ARTICLE_BODY_CAP = 3000


class GeneratorFailure(RuntimeError):
    """Raised when Claude returns invalid JSON twice in a row."""


CallClaude = Callable[[object, str], Awaitable[str]]


def build_user_message(
    *,
    articles_by_panel: dict[str, list[dict]],
    briefs_pool: list[dict],
    weather: dict,
    today: str,
    volume: str,
) -> str:
    sections = [f"Today: {today}", f"Volume: {volume}", f"Weather: {json.dumps(weather)}"]

    for panel_key, articles in articles_by_panel.items():
        sections.append(f"\n--- Panel: {panel_key} ({len(articles)} articles) ---")
        for art in articles[:10]:
            body = (art.get("content") or "")[:PER_ARTICLE_BODY_CAP]
            sections.append(
                f"\nSource: {art.get('source','?')}\n"
                f"Title: {art.get('title','?')}\n"
                f"Link: {art.get('link','?')}\n\n{body}"
            )

    sections.append(f"\n--- Briefs pool ({len(briefs_pool)} articles) ---")
    for art in briefs_pool[:20]:
        body = (art.get("content") or "")[:1500]
        sections.append(
            f"\nCategory: {art.get('category','?')}\n"
            f"Source: {art.get('source','?')}\n"
            f"Title: {art.get('title','?')}\n"
            f"Link: {art.get('link','?')}\n\n{body}"
        )

    sections.append("\n--- Schema ---")
    sections.append(json.dumps(Briefing.model_json_schema(), indent=2))
    sections.append("\nGenerate the briefing JSON now.")
    return "\n".join(sections)


async def _real_call_claude(client: anthropic.AsyncAnthropic, prompt: str) -> str:
    msg = await client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text.strip()
    # Strip accidental markdown fences
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.lstrip().lower().startswith("json"):
            raw = raw.lstrip()[4:]
        raw = raw.strip()
        if raw.endswith("```"):
            raw = raw[:-3].strip()
    return raw


async def generate(
    *,
    articles_by_panel: dict[str, list[dict]],
    briefs_pool: list[dict],
    weather: dict,
    today: str,
    volume: str,
    call_claude: CallClaude | None = None,
    client: anthropic.AsyncAnthropic | None = None,
) -> Briefing:
    """Produce a validated Briefing.

    `call_claude` is injectable for testing. When None, uses _real_call_claude
    against an AsyncAnthropic client (created if `client` is None).
    """
    if call_claude is None:
        call_claude = _real_call_claude
        if client is None:
            client = anthropic.AsyncAnthropic()

    user_msg = build_user_message(
        articles_by_panel=articles_by_panel,
        briefs_pool=briefs_pool,
        weather=weather,
        today=today,
        volume=volume,
    )

    raw = await call_claude(client, user_msg)
    try:
        return Briefing.model_validate_json(raw)
    except ValidationError as first_err:
        retry_msg = (
            user_msg
            + f"\n\nPrevious attempt failed validation:\n{first_err}\n"
            + "Fix and re-emit valid JSON only."
        )
        raw2 = await call_claude(client, retry_msg)
        try:
            return Briefing.model_validate_json(raw2)
        except ValidationError as second_err:
            raise GeneratorFailure(
                f"Claude returned invalid JSON twice. First: {first_err}; second: {second_err}"
            ) from second_err
