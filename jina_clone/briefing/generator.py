import json
from typing import Awaitable, Callable

import anthropic
from pydantic import ValidationError

from jina_clone.briefing.schema import Briefing


SYSTEM_PROMPT = """You are the editor of Rusty's daily briefing, "The Morning Fox".
Output is printed on 2 pages, newspaper-style.

Voice rules:
- Tight. Every word earns its place.
- Specific. Numbers, names, places. No hand-waving.
- Voice-neutral. No hype, no "could revolutionize", no rhetorical questions.
- Varied. Each section covers different terrain.

Structure rules:
- Lead: the single most consequential item of the day. Not the most
  sensational — the most consequential.
- Three panels (AI & Technology, National, International) in that order.
  Each panel covers the strongest story in that section. If a section has
  no strong story, write the best one you can from adjacent material in
  that bucket — don't fabricate.
- 6-9 briefs cover everything else that matters but didn't earn a panel.
  Pick what's interesting, not what's loudest.
- Pull-quote: a genuinely interesting line — verbatim from sources or a
  distilled observation. Never cheesy, never motivational.
- On-this-day: a real historical event on today's date. If uncertain of
  the date, pick a well-known event from the week.
- Data point: a real statistic from today's articles, or a widely-cited
  figure relevant to a top story.

Output: valid JSON matching the schema. No preamble, no markdown fence.
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
