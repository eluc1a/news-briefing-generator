# Slack AI/ML Digest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Post a twice-daily (9:00 / 16:45 ET) LLM-written AI/ML digest with linked items to a work Slack channel via incoming webhook.

**Architecture:** A fourth generate function in `briefing/generator.py` (reusing the `claude -p` backend + retry loop), a new `briefing/slack.py` (pure formatting + webhook POST), and a new `jobs/slack_digest.py` orchestrator with injected callables, wired through a `slack-digest` CLI subcommand. Selection reuses `fetch_section_articles(categories=["ai"], source_caps=…)` with non-overlapping time windows (morning 16.25h / afternoon 7.75h) instead of posted-URL state.

**Tech Stack:** Python 3.11, pydantic, httpx, asyncpg (existing pool helpers), `claude -p` CLI backend, pytest (asyncio auto mode, `./.venv/bin/pytest`).

**Spec:** `docs/superpowers/specs/2026-06-09-slack-ai-digest-design.md`

**Baseline:** full suite is 139 passed before this work.

---

## File map

| File | Action | Responsibility |
|---|---|---|
| `jina_clone/briefing/schema.py` | Modify | Add `DigestItem`, `SlackDigest`, `DIGEST_ITEMS_MAX` |
| `jina_clone/briefing/generator.py` | Modify | Add `generate_slack_digest` + its system prompt + user-msg builder |
| `jina_clone/briefing/slack.py` | Create | `format_digest`, `format_headlines_fallback`, `post_webhook` |
| `jina_clone/jobs/slack_digest.py` | Create | `run_slack_digest` orchestrator (injected callables) |
| `jina_clone/cli.py` | Modify | `slack-digest` subcommand, windows/labels constants, wiring |
| `jina_clone/config.py` | Modify | `Settings.slack_webhook_url` (optional) |
| `.env.example` | Modify | Add `SLACK_WEBHOOK_URL` |
| `README.md` | Modify | Short "Slack digest" section |
| `tests/test_briefing_generator.py` | Modify | Digest generation tests (append) |
| `tests/test_briefing_schema.py` | Modify | `SlackDigest` bounds test (append) |
| `tests/test_briefing_slack.py` | Create | Formatting + webhook tests |
| `tests/test_jobs_slack_digest.py` | Create | Orchestrator tests |
| `tests/test_config.py` | Modify | `SLACK_WEBHOOK_URL` settings test (append) |

Notes for the engineer:

- Tests are bare `async def test_*` — pytest-asyncio runs in auto mode
  (configured in `pyproject.toml`). Do not add `@pytest.mark.asyncio`.
- Always run tests with `./.venv/bin/pytest` (system pytest lacks the deps).
- None of these tests touch the DB; the real-Postgres `db` fixture is not
  needed. `fetch_section_articles` itself is already covered in
  `test_storage.py`.
- Commit after each task with the trailer
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Schema models + `generate_slack_digest`

**Files:**
- Modify: `jina_clone/briefing/schema.py` (append after `Brief`, ~line 70)
- Modify: `jina_clone/briefing/generator.py`
- Test: `tests/test_briefing_schema.py`, `tests/test_briefing_generator.py`

- [ ] **Step 1: Write the failing schema test**

Append to `tests/test_briefing_schema.py`:

```python
# ------------- slack digest -------------

def test_slack_digest_bounds():
    from pydantic import ValidationError as VErr

    from jina_clone.briefing.schema import DigestItem, SlackDigest

    item = DigestItem(url="https://a", title="T", blurb="B")
    digest = SlackDigest(lead="L", items=[item])
    assert digest.items[0].url == "https://a"

    with pytest.raises(VErr):
        SlackDigest(lead="L", items=[])          # min 1
    with pytest.raises(VErr):
        SlackDigest(lead="L", items=[item] * 11)  # max 10
```

(`pytest` is already imported in that file; if not, add `import pytest`.)

- [ ] **Step 2: Run it to verify it fails**

Run: `./.venv/bin/pytest tests/test_briefing_schema.py::test_slack_digest_bounds -v`
Expected: FAIL with `ImportError: cannot import name 'DigestItem'`

- [ ] **Step 3: Add the models to `schema.py`**

Append after the `Brief` class in `jina_clone/briefing/schema.py`:

```python
DIGEST_ITEMS_MAX = 10


class DigestItem(BaseModel):
    url: str
    title: str
    blurb: str


class SlackDigest(BaseModel):
    """Output of the slack-digest LLM call. Standalone — not part of
    Briefing. min 1 (a thin window may have <6 articles), max 10."""
    lead: str
    items: list[DigestItem] = Field(min_length=1, max_length=DIGEST_ITEMS_MAX)
```

- [ ] **Step 4: Run the schema test to verify it passes**

Run: `./.venv/bin/pytest tests/test_briefing_schema.py -v`
Expected: all PASS

- [ ] **Step 5: Write the failing generator tests**

Append to `tests/test_briefing_generator.py`. Also extend the existing
import block at the top: add `generate_slack_digest` and
`_slack_digest_system_prompt` to the `from jina_clone.briefing.generator
import (...)` list, and `SlackDigest` to the `from
jina_clone.briefing.schema import (...)` list.

```python
# ------------- slack digest -------------

def _digest_payload(urls=("https://a", "https://b")) -> str:
    return json.dumps({
        "lead": "Two stories matter today.",
        "items": [
            {"url": u, "title": f"Title {i}", "blurb": "One line."}
            for i, u in enumerate(urls)
        ],
    })


async def test_slack_digest_happy_path():
    async def fake(client, prompt: str) -> str:
        return _digest_payload()

    digest = await generate_slack_digest(
        articles=_articles(), edition_label="Morning",
        call_llm=fake, client=None,
    )
    assert isinstance(digest, SlackDigest)
    assert [i.url for i in digest.items] == ["https://a", "https://b"]


async def test_slack_digest_retries_once_on_bad_json():
    attempts = [json.dumps({"lead": "no items"}), _digest_payload()]

    async def fake(client, prompt: str) -> str:
        return attempts.pop(0)

    digest = await generate_slack_digest(
        articles=_articles(), edition_label="Morning",
        call_llm=fake, client=None,
    )
    assert isinstance(digest, SlackDigest)


async def test_slack_digest_rejects_hallucinated_url():
    async def fake(client, prompt: str) -> str:
        return _digest_payload(urls=("https://a", "https://hallucinated"))

    with pytest.raises(GeneratorFailure):
        await generate_slack_digest(
            articles=_articles(), edition_label="Morning",
            call_llm=fake, client=None,
        )


async def test_slack_digest_rejects_duplicate_urls():
    async def fake(client, prompt: str) -> str:
        return _digest_payload(urls=("https://a", "https://a"))

    with pytest.raises(GeneratorFailure):
        await generate_slack_digest(
            articles=_articles(), edition_label="Morning",
            call_llm=fake, client=None,
        )


def test_slack_digest_prompt_carries_edition():
    morning = _slack_digest_system_prompt("Morning")
    afternoon = _slack_digest_system_prompt("Afternoon")
    assert "Morning" in morning
    assert "Afternoon" in afternoon
    assert "Morning" not in afternoon
    assert "VOICE RULES" in morning
```

- [ ] **Step 6: Run them to verify they fail**

Run: `./.venv/bin/pytest tests/test_briefing_generator.py -v -k slack_digest`
Expected: FAIL with `ImportError: cannot import name 'generate_slack_digest'`

- [ ] **Step 7: Implement in `generator.py`**

Three additions, mirroring the `generate_briefs` pattern exactly.

(a) Extend the schema import at the top of the file:

```python
from jina_clone.briefing.schema import (
    Brief, BRIEFS_COUNT_MAX, BRIEFS_COUNT_MIN, FrontMatter, Panel, SlackDigest,
)
```

(b) Prompts — add after `_briefs_system_prompt` (~line 267):

```python
SLACK_DIGEST_SCOPE = """SCOPE: a twice-daily AI/ML digest posted to a work
Slack channel of software engineers. Prefer: model releases and benchmark
results, agent techniques and harnesses, notable open-source repos and
tools, applied LLM engineering, consequential industry news. Deprioritize:
incremental arXiv papers without code or results, funding gossip, opinion
pieces."""


SLACK_DIGEST_STRUCTURE_RULES = """STRUCTURE — every field required:
- lead: 2-3 sentences, 30-60 words, on the most consequential story or
  theme across the input articles. Facts only. NEVER exceed 60 words.
- items: 6-10 entries, most consequential first. If fewer than 6 input
  articles are provided, emit one entry per article instead. Each entry:
    - url: EXACTLY the `Link` value of the source article, verbatim. If
      you alter or invent a URL the digest will be rejected.
    - title: ≤ 12 words, concrete subject + action. Rewrite vague or
      clickbait headlines factually.
    - blurb: 10-20 words, facts only — what it is and why a working
      AI/ML engineer would care. NEVER exceed 20 words.
- Never emit two items with the same url. Never fabricate items."""


def _slack_digest_system_prompt(edition_label: str) -> str:
    return f"""You are the editor of the {edition_label} edition of an
AI/ML digest posted to a work Slack channel.

{SLACK_DIGEST_SCOPE}

{VOICE_RULES}

{SLACK_DIGEST_STRUCTURE_RULES}

Output: valid JSON matching the SlackDigest schema below. No preamble. No
markdown fence.
"""
```

(c) User-msg builder — add after `_build_briefs_user_msg` (~line 344):

```python
def _build_slack_digest_user_msg(*, articles: list[dict]) -> str:
    parts = [f"Candidate articles ({len(articles)})"]
    for art in articles:
        parts.append("")
        parts.append(_format_article(art, body_cap=1500))
    parts.append("")
    parts.append("--- Schema ---")
    parts.append(json.dumps(SlackDigest.model_json_schema(), indent=2))
    parts.append("")
    parts.append("Emit the SlackDigest JSON now.")
    return "\n".join(parts)
```

(d) Public function — add after `generate_briefs` at the end of the file:

```python
async def generate_slack_digest(
    *,
    articles: list[dict],
    edition_label: str,
    call_llm: CallLLM | None = None,
    client: AsyncAnthropic | None = None,
) -> SlackDigest:
    system_prompt = _slack_digest_system_prompt(edition_label)
    if call_llm is None:
        call_llm = _build_default_call_llm(system_prompt, client)

    user_msg = _build_slack_digest_user_msg(articles=articles)
    valid_urls = {a.get("link") for a in articles}

    def parse(raw: str) -> SlackDigest:
        digest = SlackDigest.model_validate_json(raw)
        seen: set[str] = set()
        for item in digest.items:
            if item.url not in valid_urls:
                raise ValueError(
                    f"item url {item.url!r} not in input article links"
                )
            if item.url in seen:
                raise ValueError(f"duplicate item url {item.url!r}")
            seen.add(item.url)
        return digest

    return await _call_with_retry(
        call_llm=call_llm, client=client,
        user_msg=user_msg,
        parse=parse,
    )
```

- [ ] **Step 8: Run the task's tests, then the full suite**

Run: `./.venv/bin/pytest tests/test_briefing_generator.py tests/test_briefing_schema.py -v`
Expected: all PASS
Run: `./.venv/bin/pytest -q`
Expected: 145 passed (139 baseline + 6 new)

- [ ] **Step 9: Commit**

```bash
git add jina_clone/briefing/schema.py jina_clone/briefing/generator.py \
  tests/test_briefing_schema.py tests/test_briefing_generator.py
git commit -m "feat(briefing): generate_slack_digest — LLM digest with URL validation"
```

---

### Task 2: Slack formatting + webhook poster

**Files:**
- Create: `jina_clone/briefing/slack.py`
- Test: `tests/test_briefing_slack.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_briefing_slack.py`:

```python
from unittest.mock import patch

import httpx
import pytest

from jina_clone.briefing.schema import DigestItem, SlackDigest
from jina_clone.briefing.slack import (
    format_digest,
    format_headlines_fallback,
    post_webhook,
)


def _digest() -> SlackDigest:
    return SlackDigest(
        lead="Big day for agents.",
        items=[
            DigestItem(url="https://a", title="T & A <tag>", blurb="b1"),
            DigestItem(url="https://b", title="Plain", blurb="b2"),
        ],
    )


def test_format_digest_structure():
    payload = format_digest(
        _digest(), edition_label="Morning", date_label="Tue Jun 9",
    )
    assert payload["unfurl_links"] is False
    assert payload["unfurl_media"] is False
    text = payload["text"]
    assert text.startswith("*🤖 AI/ML Morning Digest — Tue Jun 9*")
    assert "Big day for agents." in text
    assert "• <https://b|Plain> — b2" in text


def test_format_digest_escapes_mrkdwn_specials():
    # Slack mrkdwn requires &, <, > escaped in text (else <tag> becomes
    # a broken link token). & must be replaced first.
    text = format_digest(
        _digest(), edition_label="Morning", date_label="Tue Jun 9",
    )["text"]
    assert "T &amp; A &lt;tag&gt;" in text
    assert "<tag>" not in text


def test_fallback_caps_items_and_notes_degraded():
    articles = [
        {"link": f"https://x/{i}", "title": f"t{i}"} for i in range(15)
    ]
    payload = format_headlines_fallback(
        articles, edition_label="Afternoon", date_label="Tue Jun 9",
    )
    text = payload["text"]
    assert text.startswith("*🤖 AI/ML Afternoon Digest — Tue Jun 9*")
    assert "headlines only" in text
    assert "<https://x/9|t9>" in text
    assert "https://x/10" not in text  # capped at 10
    assert payload["unfurl_links"] is False


def test_fallback_handles_missing_title():
    payload = format_headlines_fallback(
        [{"link": "https://x", "title": None}],
        edition_label="Morning", date_label="Tue Jun 9",
    )
    assert "<https://x|https://x>" in payload["text"]


def test_post_webhook_posts_json():
    with patch("jina_clone.briefing.slack.httpx.post") as post:
        post.return_value.raise_for_status.return_value = None
        post_webhook("https://hooks.slack.com/services/X", {"text": "hi"})
        post.assert_called_once()
        assert post.call_args.args[0] == "https://hooks.slack.com/services/X"
        assert post.call_args.kwargs["json"] == {"text": "hi"}


def test_post_webhook_raises_on_http_error():
    with patch("jina_clone.briefing.slack.httpx.post") as post:
        post.return_value.raise_for_status.side_effect = httpx.HTTPStatusError(
            "boom", request=None, response=None,
        )
        with pytest.raises(httpx.HTTPStatusError):
            post_webhook("https://hooks.slack.com/services/X", {"text": "hi"})
```

- [ ] **Step 2: Run them to verify they fail**

Run: `./.venv/bin/pytest tests/test_briefing_slack.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jina_clone.briefing.slack'`

- [ ] **Step 3: Implement `jina_clone/briefing/slack.py`**

```python
"""Slack webhook formatting + posting for the AI/ML digest.

v1 is webhook-only: no threads, no reactions (webhooks can't read
reactions or learn their own message ts). `post_webhook` is the single
seam to swap for a bot-token client (chat.postMessage) when voting lands
— see the 2026-06-09 spec.
"""
import httpx

from jina_clone.briefing.schema import SlackDigest

FALLBACK_MAX_ITEMS = 10

# Order matters: & first, or we double-escape the entities we just made.
_MRKDWN_ESCAPES = (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"))


def _escape(text: str) -> str:
    for ch, rep in _MRKDWN_ESCAPES:
        text = text.replace(ch, rep)
    return text


def _header(edition_label: str, date_label: str) -> str:
    return f"*🤖 AI/ML {edition_label} Digest — {date_label}*"


def format_digest(
    digest: SlackDigest, *, edition_label: str, date_label: str,
) -> dict:
    lines = [_header(edition_label, date_label), "", _escape(digest.lead), ""]
    for item in digest.items:
        lines.append(
            f"• <{item.url}|{_escape(item.title)}> — {_escape(item.blurb)}"
        )
    return {
        "text": "\n".join(lines),
        "unfurl_links": False,
        "unfurl_media": False,
    }


def format_headlines_fallback(
    articles: list[dict], *, edition_label: str, date_label: str,
) -> dict:
    """Degraded variant for LLM failure: linked headlines, newest-first
    (input order from fetch_section_articles), capped at 10."""
    lines = [
        _header(edition_label, date_label),
        "",
        "_LLM digest unavailable — headlines only._",
        "",
    ]
    for art in articles[:FALLBACK_MAX_ITEMS]:
        title = art.get("title") or art["link"]
        lines.append(f"• <{art['link']}|{_escape(title)}>")
    return {
        "text": "\n".join(lines),
        "unfurl_links": False,
        "unfurl_media": False,
    }


def post_webhook(url: str, payload: dict) -> None:
    response = httpx.post(url, json=payload, timeout=15)
    response.raise_for_status()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_briefing_slack.py -v`
Expected: 6 PASS

- [ ] **Step 5: Commit**

```bash
git add jina_clone/briefing/slack.py tests/test_briefing_slack.py
git commit -m "feat(briefing): Slack digest formatting + webhook poster"
```

---

### Task 3: `run_slack_digest` orchestrator

**Files:**
- Create: `jina_clone/jobs/slack_digest.py`
- Test: `tests/test_jobs_slack_digest.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_jobs_slack_digest.py`:

```python
import pytest

from jina_clone.briefing.generator import GeneratorFailure
from jina_clone.briefing.schema import DigestItem, SlackDigest
from jina_clone.jobs.slack_digest import run_slack_digest


def _rows():
    return [
        {"title": "t1", "link": "https://a", "source": "S1", "content": "c1"},
        {"title": "t2", "link": "https://b", "source": "S2", "content": "c2"},
    ]


def _digest():
    return SlackDigest(
        lead="L",
        items=[DigestItem(url="https://a", title="T", blurb="B")],
    )


class Harness:
    """Injected fakes + recorders for run_slack_digest."""

    def __init__(self, rows=None, gen_fails=False, post_fails=False):
        self.rows = _rows() if rows is None else rows
        self.gen_fails = gen_fails
        self.post_fails = post_fails
        self.fetch_kwargs: dict = {}
        self.posted: list[tuple] = []
        self.notified: list[dict] = []

    async def fetch(self, pool, **kwargs):
        self.fetch_kwargs = kwargs
        return self.rows

    async def generate(self, *, articles, edition_label):
        if self.gen_fails:
            raise GeneratorFailure("claude -p exited 1")
        return _digest()

    def format_digest(self, digest, *, edition_label, date_label):
        return {"text": "digest"}

    def format_fallback(self, articles, *, edition_label, date_label):
        return {"text": "fallback"}

    def post(self, url, payload):
        if self.post_fails:
            raise RuntimeError("webhook down")
        self.posted.append((url, payload))

    def notify_failure(self, **kwargs):
        self.notified.append(kwargs)

    async def run(self):
        return await run_slack_digest(
            None,
            webhook_url="https://hooks.slack.com/services/X",
            window_hours=7.75,
            edition_label="Afternoon",
            date_label="Tue Jun 9",
            title="AI/ML Slack Digest",
            ntfy_topic="fox-briefings",
            source_caps={"arXiv cs.AI": 2},
            fetch_articles=self.fetch,
            generate_digest=self.generate,
            format_digest=self.format_digest,
            format_fallback=self.format_fallback,
            post=self.post,
            notify_failure=self.notify_failure,
        )


async def test_happy_path_posts_digest_no_notify():
    h = Harness()
    result = await h.run()
    assert h.posted == [
        ("https://hooks.slack.com/services/X", {"text": "digest"})
    ]
    assert h.notified == []
    assert result == {"degraded": False, "article_count": 2}


async def test_fetch_receives_window_caps_and_category():
    h = Harness()
    await h.run()
    assert h.fetch_kwargs["categories"] == ["ai"]
    assert h.fetch_kwargs["since_hours"] == 7.75
    assert h.fetch_kwargs["limit"] == 40
    assert h.fetch_kwargs["source_caps"] == {"arXiv cs.AI": 2}


async def test_llm_failure_posts_fallback_and_notifies():
    h = Harness(gen_fails=True)
    result = await h.run()
    assert h.posted == [
        ("https://hooks.slack.com/services/X", {"text": "fallback"})
    ]
    assert len(h.notified) == 1
    assert "fallback" in h.notified[0]["reason"]
    assert result == {"degraded": True, "article_count": 2}


async def test_zero_articles_skips_post_and_notify():
    h = Harness(rows=[])
    result = await h.run()
    assert result is None
    assert h.posted == []
    assert h.notified == []


async def test_webhook_failure_notifies_and_raises():
    h = Harness(post_fails=True)
    with pytest.raises(RuntimeError):
        await h.run()
    assert len(h.notified) == 1
    assert "webhook" in h.notified[0]["reason"].lower()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `./.venv/bin/pytest tests/test_jobs_slack_digest.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jina_clone.jobs.slack_digest'`

- [ ] **Step 3: Implement `jina_clone/jobs/slack_digest.py`**

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_jobs_slack_digest.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add jina_clone/jobs/slack_digest.py tests/test_jobs_slack_digest.py
git commit -m "feat(jobs): run_slack_digest orchestrator with fallback + notify policy"
```

---

### Task 4: Settings, CLI wiring, live E2E, docs

**Files:**
- Modify: `jina_clone/config.py` (Settings dataclass + `from_env`)
- Modify: `jina_clone/cli.py`
- Modify: `.env.example`, `README.md`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing settings test**

Append to `tests/test_config.py` (it already has env-manipulation tests —
follow the same monkeypatch style used there; minimal env shown):

```python
def test_settings_slack_webhook_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    from jina_clone.config import Settings

    assert Settings.from_env().slack_webhook_url is None

    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/X")
    assert (
        Settings.from_env().slack_webhook_url
        == "https://hooks.slack.com/services/X"
    )
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./.venv/bin/pytest tests/test_config.py::test_settings_slack_webhook_url -v`
Expected: FAIL with `TypeError` / `AttributeError` (no `slack_webhook_url` field)

- [ ] **Step 3: Add the setting**

In `jina_clone/config.py`, `Settings` dataclass — add among the defaulted
fields (after `fred_api_key`, before `api_keys`):

```python
    slack_webhook_url: str | None = None
```

In `from_env`, add to the `cls(...)` call (after `fred_api_key=...`):

```python
            slack_webhook_url=os.getenv("SLACK_WEBHOOK_URL") or None,
```

Run: `./.venv/bin/pytest tests/test_config.py -v` → all PASS

- [ ] **Step 4: Wire the CLI**

In `jina_clone/cli.py`:

(a) Add imports — `import json` to the stdlib block at the top, and with
the other project imports:

```python
from jina_clone.briefing import slack as briefing_slack
from jina_clone.jobs.slack_digest import run_slack_digest
```

(b) Add constants near `EDITION_TITLES` (~line 188):

```python
# Non-overlapping windows matching the cron cadence (9:00 / 16:45 ET):
# morning covers since yesterday 16:45, afternoon covers since 9:00.
SLACK_DIGEST_WINDOWS = {"morning": 16.25, "afternoon": 7.75}
SLACK_DIGEST_EDITION_LABELS = {"morning": "Morning", "afternoon": "Afternoon"}
SLACK_DIGEST_TITLE = "AI/ML Slack Digest"
```

(c) Add the runner after `_briefing_run`:

```python
async def _run_slack_digest(settings: Settings, *, edition: str, dry_run: bool):
    if not settings.slack_webhook_url and not dry_run:
        raise SystemExit(
            "SLACK_WEBHOOK_URL is required for slack-digest (set it in .env)"
        )
    cfg = load_briefing_config(settings.briefing_categories_file)

    post = briefing_slack.post_webhook
    if dry_run:
        def post(url: str, payload: dict) -> None:
            print(json.dumps(payload, indent=2, ensure_ascii=False))

    briefing_generator.reset_usage()
    pool = await create_pool(settings.database_url)
    try:
        await run_slack_digest(
            pool,
            webhook_url=settings.slack_webhook_url or "dry-run",
            window_hours=SLACK_DIGEST_WINDOWS[edition],
            edition_label=SLACK_DIGEST_EDITION_LABELS[edition],
            date_label=datetime.now().strftime("%a %b %-d"),
            title=SLACK_DIGEST_TITLE,
            ntfy_topic=settings.ntfy_topic,
            source_caps=dict(cfg.source_caps),
            fetch_articles=fetch_section_articles,
            generate_digest=briefing_generator.generate_slack_digest,
            format_digest=briefing_slack.format_digest,
            format_fallback=briefing_slack.format_headlines_fallback,
            post=post,
            notify_failure=briefing_notify.notify_failure,
        )
    finally:
        await pool.close()
        totals = briefing_generator.pop_usage_totals()
        if totals["calls"]:
            logging.info(
                "slack digest llm totals (%s): calls=%d input=%d output=%d",
                edition, totals["calls"], totals["input"], totals["output"],
            )
```

(d) In `main()`, add the subparser after the briefing block:

```python
    slack_p = sub.add_parser("slack-digest")
    slack_p.add_argument(
        "--edition", required=True, choices=["morning", "afternoon"],
        help="morning (9:00 ET, 16.25h window) or afternoon (16:45 ET, 7.75h window)",
    )
    slack_p.add_argument(
        "--dry-run", action="store_true",
        help="Print the Slack payload to stdout instead of posting",
    )
```

and the dispatch branch:

```python
    elif args.cmd == "slack-digest":
        asyncio.run(
            _run_slack_digest(settings, edition=args.edition, dry_run=args.dry_run)
        )
```

- [ ] **Step 5: Full suite + import smoke check**

Run: `./.venv/bin/pytest -q`
Expected: 157 passed (139 baseline + 18 new: 6 in Task 1, 6 in Task 2, 5 in Task 3, 1 in Task 4), 0 failures
Run: `./.venv/bin/python -m jina_clone slack-digest --help`
Expected: usage text showing `--edition` and `--dry-run`

- [ ] **Step 6: Live E2E (real DB + real claude -p, no Slack post)**

Per CLAUDE.md, run the real pipeline before polish. This reads production
`mcp_news` (read-only) and makes one real `claude -p` call:

Run: `./.venv/bin/python -m jina_clone slack-digest --edition=afternoon --dry-run`

Verify in the printed payload:
- `text` starts with `*🤖 AI/ML Afternoon Digest — <today>*`
- 6–10 `• <url|title> — blurb` lines; every URL is a real article link
- no markdown fences, no escaped-entity garbage in titles
- `unfurl_links: false` present

If the LLM output shape surprises (e.g. systematically <6 items, lead too
long), fix the prompt rules in `generator.py` now, not after Task 4 ships.

- [ ] **Step 7: `.env.example` + README**

Append to `.env.example`:

```
# Slack incoming webhook for the twice-daily AI/ML digest (slack-digest cmd)
SLACK_WEBHOOK_URL=
```

Add a short README section after "Running a briefing manually":

```markdown
## Slack AI/ML digest

Twice-daily digest of `category: ai` articles posted to a work Slack
channel via incoming webhook (`SLACK_WEBHOOK_URL` in `.env`).

```bash
./.venv/bin/python -m jina_clone slack-digest --edition=morning    # 9:00 ET
./.venv/bin/python -m jina_clone slack-digest --edition=afternoon  # 16:45 ET
./.venv/bin/python -m jina_clone slack-digest --edition=afternoon --dry-run  # print, don't post
```

Editions use non-overlapping windows (morning 16.25h, afternoon 7.75h),
so no article appears twice. On LLM failure the digest degrades to
headlines-only and sends an ntfy alert. Design:
`docs/superpowers/specs/2026-06-09-slack-ai-digest-design.md`.
```

- [ ] **Step 8: Commit**

```bash
git add jina_clone/config.py jina_clone/cli.py tests/test_config.py \
  .env.example README.md
git commit -m "feat(cli): slack-digest subcommand — settings, windows, dry-run"
```

---

## User setup checklist (manual, after Task 4)

Not automatable from this repo — walk the user through these:

1. **Create the incoming webhook** in the work Slack workspace
   (api.slack.com → Create App → Incoming Webhooks → pick the team
   channel). Put the URL in `.env` as `SLACK_WEBHOOK_URL=`.
2. **One real post test:**
   `./.venv/bin/python -m jina_clone slack-digest --edition=afternoon`
   and eyeball the message in the channel.
3. **Host crontab** (same crontab as the briefing entries; user runs
   `crontab -e`):

   ```cron
   0 9 * * *  cd /home/elucia/dev/jina-clone && ./.venv/bin/python -m jina_clone slack-digest --edition=morning   >> logs/slack-digest.log 2>&1
   45 16 * * * cd /home/elucia/dev/jina-clone && ./.venv/bin/python -m jina_clone slack-digest --edition=afternoon >> logs/slack-digest.log 2>&1
   ```

   ⚠️ `logs/` is root-owned on fox (known host-cron gotcha). Before the
   first firing: `sudo touch logs/slack-digest.log && sudo chown elucia
   logs/slack-digest.log` — or point the redirect somewhere elucia owns.

## Explicitly out of scope (from the spec)

- Voting/reactions, threading, message-record storage (needs a Slack
  bot token — `post_webhook` is the swap seam).
- Literal RSS/Atom output.
- Any change to `run_briefing`, the printer, or the web pipeline.
