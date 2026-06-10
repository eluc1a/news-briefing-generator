# AI/ML Digest RSS Feed Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Slack digest's webhook delivery with a public RSS 2.0 feed (+ per-edition HTML pages) that Slack's first-party `/feed` app polls.

**Architecture:** New `briefing/feed.py` (pure rendering + file publishing, stdlib-only XML), adapted `jobs/slack_digest.py` (format/post callables → `publish`/`publish_fallback` pair), settings swap (`SLACK_WEBHOOK_URL` → `FEED_BASE_URL` + `FEED_OUTPUT_DIR`), CLI rewiring, then webhook code removal. `feed.xml` is rebuilt by scanning `{date}-{edition}.json` records (same self-healing pattern as `web.rebuild_index`), capped at the newest 20 entries.

**Tech Stack:** Python 3.11, pydantic, stdlib (`xml.sax.saxutils`, `email.utils`, `json`, `re`), pytest (asyncio auto mode, `./.venv/bin/pytest`).

**Spec:** `docs/superpowers/specs/2026-06-09-ai-digest-rss-feed-design.md`

**Baseline:** full suite is 161 passed before this work.

**HARD CONSTRAINT:** the briefing pipeline is untouched — do not modify `jobs/briefing.py`, `briefing/renderer.py`, `briefing/printer.py`, `briefing/web.py`, `briefing/run_web.py`, `briefing/generator.py`, `templates/`, or `static/`.

---

## File map

| File | Action | Responsibility |
|---|---|---|
| `jina_clone/briefing/feed.py` | Create | record building, HTML page + RSS XML rendering, publish + rebuild-by-scan |
| `tests/test_briefing_feed.py` | Create | rendering/escaping, publish outputs, rebuild order + cap |
| `jina_clone/jobs/slack_digest.py` | Rewrite | orchestrator: publish/publish_fallback seam replaces format+post |
| `tests/test_jobs_slack_digest.py` | Rewrite | same 6 scenarios against the new seam |
| `jina_clone/config.py` | Modify | drop `slack_webhook_url`; add `feed_base_url`, `feed_output_dir` |
| `tests/test_config.py` | Modify | replace webhook test with feed-settings test |
| `jina_clone/cli.py` | Modify | rewire `slack-digest`; dry-run prints rendered outputs; drop webhook bits |
| `jina_clone/briefing/slack.py` | Delete | webhook delivery (git history keeps it) |
| `tests/test_briefing_slack.py` | Delete | with it |
| `.env.example` | Modify | `SLACK_WEBHOOK_URL` → `FEED_BASE_URL` / `FEED_OUTPUT_DIR` |
| `.gitignore` | Modify | add `feeds/` |
| `README.md` | Modify | rewrite the "Slack AI/ML digest" section for RSS |

Notes for the engineer:

- Tests are bare `async def test_*` / `def test_*` — pytest-asyncio runs in
  auto mode (configured in `pyproject.toml`). Do not add `@pytest.mark.asyncio`.
- Always run tests with `./.venv/bin/pytest` (system pytest lacks the deps).
- None of these tests touch the DB; the real-Postgres `db` fixture is not needed.
- Never `git add -A` / `git add .` in this repo — stage exact paths only.
- Commit after each task with the trailer
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Expected test totals after each task: T1 167 → T2 167 → T3 167 → T4 159
  (T1 adds 6; T2/T3 rewrite in place; T4 deletes the 8 webhook tests).

---

### Task 1: `briefing/feed.py` — rendering + publishing

Purely additive; `slack.py` and everything else untouched.

**Files:**
- Create: `jina_clone/briefing/feed.py`
- Test: `tests/test_briefing_feed.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_briefing_feed.py`:

```python
import json
from datetime import datetime, timezone

from jina_clone.briefing.feed import (
    FEED_MAX_ENTRIES,
    publish_digest,
    publish_fallback,
    rebuild_feed,
)
from jina_clone.briefing.schema import DigestItem, SlackDigest

GEN_AT = datetime(2026, 6, 9, 8, 45, tzinfo=timezone.utc)
BASE = "https://feeds.example.com/ai-digest"


def _digest() -> SlackDigest:
    return SlackDigest(
        lead="Big day for agents & <tools>.",
        items=[
            DigestItem(url="https://a?x=1&y=2", title="T & A <tag>", blurb="b1"),
            DigestItem(url="https://b", title="Plain", blurb="b2"),
        ],
    )


def _publish(tmp_path, digest=None):
    return publish_digest(
        digest or _digest(),
        out_dir=tmp_path, base_url=BASE,
        iso_date="2026-06-09", edition="morning",
        edition_label="Morning", date_label="Tue Jun 9",
        generated_at=GEN_AT,
    )


def _record(iso_date: str, edition: str) -> dict:
    """A minimal degraded record, for rebuild-by-scan tests."""
    return {
        "date": iso_date, "edition": edition,
        "edition_label": edition.title(), "date_label": iso_date,
        "generated_at": GEN_AT.isoformat(), "degraded": True,
        "digest": None,
        "headlines": [{"link": "https://x", "title": "t"}],
    }


def test_publish_digest_writes_all_outputs(tmp_path):
    page = _publish(tmp_path)
    assert page == tmp_path / "2026-06-09-morning.html"
    assert (tmp_path / "2026-06-09-morning.json").exists()
    feed = (tmp_path / "feed.xml").read_text()
    assert "<title>AI/ML Morning Digest — Tue Jun 9</title>" in feed
    assert (
        '<guid isPermaLink="true">'
        f"{BASE}/2026-06-09-morning.html</guid>"
    ) in feed
    assert "<pubDate>Tue, 09 Jun 2026 08:45:00 +0000</pubDate>" in feed


def test_page_html_escapes_and_links(tmp_path):
    page = _publish(tmp_path).read_text()
    assert "T &amp; A &lt;tag&gt;" in page
    assert "<tag>" not in page
    assert '<a href="https://a?x=1&amp;y=2">' in page
    assert "Big day for agents &amp; &lt;tools&gt;." in page
    assert "Generated 2026-06-09 08:45 UTC" in page


def test_feed_description_is_cdata_with_body(tmp_path):
    _publish(tmp_path)
    feed = (tmp_path / "feed.xml").read_text()
    assert "<description><![CDATA[" in feed
    assert "Big day for agents &amp; &lt;tools&gt;." in feed


def test_publish_fallback_degraded_caps_and_defaults(tmp_path):
    articles = [{"link": f"https://x/{i}", "title": f"t{i}"} for i in range(8)]
    articles.append({"link": None, "title": "no link"})
    articles.append({"link": "https://x/notitle", "title": None})
    articles += [{"link": f"https://y/{i}", "title": f"u{i}"} for i in range(5)]
    page = publish_fallback(
        articles,
        out_dir=tmp_path, base_url=BASE,
        iso_date="2026-06-09", edition="afternoon",
        edition_label="Afternoon", date_label="Tue Jun 9",
        generated_at=GEN_AT,
    ).read_text()
    assert "LLM digest unavailable" in page
    assert '<a href="https://x/7">t7</a>' in page
    assert "no link" not in page                              # linkless skipped
    assert '<a href="https://x/notitle">https://x/notitle</a>' in page
    assert "https://y/0" not in page                          # capped at 10 slots


def test_rebuild_orders_newest_first_and_caps(tmp_path):
    for day in range(1, 13):                  # 12 days × 2 editions = 24 records
        for edition in ("morning", "afternoon"):
            iso = f"2026-06-{day:02d}"
            (tmp_path / f"{iso}-{edition}.json").write_text(
                json.dumps(_record(iso, edition))
            )
    rebuild_feed(tmp_path, base_url=BASE)
    feed = (tmp_path / "feed.xml").read_text()
    assert feed.count("<item>") == FEED_MAX_ENTRIES
    # newest first; afternoon outranks morning within a day
    assert feed.index("2026-06-12-afternoon.html") < feed.index("2026-06-12-morning.html")
    # oldest two days fall off the 20-entry cap
    assert "2026-06-02" not in feed
    assert "2026-06-01" not in feed


def test_rebuild_ignores_foreign_files(tmp_path):
    (tmp_path / "feed.xml").write_text("old")
    (tmp_path / "notes.json").write_text("{}")
    (tmp_path / "2026-06-09-morning.json").write_text(
        json.dumps(_record("2026-06-09", "morning"))
    )
    rebuild_feed(tmp_path, base_url=BASE)
    feed = (tmp_path / "feed.xml").read_text()
    assert feed.count("<item>") == 1
    assert "old" not in feed
```

- [ ] **Step 2: Run them to verify they fail**

Run: `./.venv/bin/pytest tests/test_briefing_feed.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jina_clone.briefing.feed'`

- [ ] **Step 3: Implement `jina_clone/briefing/feed.py`**

```python
"""RSS feed + HTML page publishing for the AI/ML digest.

Delivery is a public RSS 2.0 feed polled by Slack's first-party /feed
app (the work workspace allows no app installs, so webhooks and bot
tokens are out). One feed entry per edition, linking to a standalone
HTML page. feed.xml is rebuilt by scanning {date}-{edition}.json
records — rebuild-by-scan self-heals, same pattern as
web.rebuild_index. See
docs/superpowers/specs/2026-06-09-ai-digest-rss-feed-design.md.
"""
import json
import re
from datetime import datetime
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape

from jina_clone.briefing.schema import SlackDigest

FALLBACK_MAX_ITEMS = 10
FEED_MAX_ENTRIES = 20
FEED_TITLE = "AI/ML Digest"
FEED_DESCRIPTION = "Twice-daily LLM digest of AI/ML news, papers, and tools."

# Afternoon publishes after morning, so it is "newer" within a day.
_EDITION_ORDER = {"morning": 0, "afternoon": 1}
_NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(morning|afternoon)\.json$")


def _attr(value: str) -> str:
    return escape(value, {'"': "&quot;"})


def _entry_title(edition_label: str, date_label: str) -> str:
    return f"AI/ML {edition_label} Digest — {date_label}"


def _digest_body_html(digest: SlackDigest) -> str:
    lines = [f'<p class="lead">{escape(digest.lead)}</p>', "<ul>"]
    for item in digest.items:
        lines.append(
            f'<li><a href="{_attr(item.url)}">{escape(item.title)}</a>'
            f" — {escape(item.blurb)}</li>"
        )
    lines.append("</ul>")
    return "\n".join(lines)


def _fallback_body_html(headlines: list[dict]) -> str:
    """Degraded variant for LLM failure: linked headlines, newest-first
    (input order from fetch_section_articles), capped at 10."""
    lines = [
        '<p class="degraded">LLM digest unavailable — headlines only.</p>',
        "<ul>",
    ]
    for art in headlines[:FALLBACK_MAX_ITEMS]:
        link = art.get("link")
        if not link:
            continue
        title = art.get("title") or link
        lines.append(f'<li><a href="{_attr(link)}">{escape(title)}</a></li>')
    lines.append("</ul>")
    return "\n".join(lines)


def _record_body_html(record: dict) -> str:
    if record["degraded"]:
        return _fallback_body_html(record["headlines"])
    return _digest_body_html(SlackDigest.model_validate(record["digest"]))


_PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
body {{ font-family: Georgia, serif; max-width: 42rem; margin: 2rem auto;
       padding: 0 1rem; color: #1a1a1a; }}
h1 {{ font-size: 1.4rem; border-bottom: 2px solid #1a1a1a;
     padding-bottom: .4rem; }}
.lead {{ font-size: 1.05rem; }}
li {{ margin: .6rem 0; }}
.degraded {{ color: #8a6d3b; font-style: italic; }}
footer {{ margin-top: 2rem; font-size: .8rem; color: #777; }}
</style>
</head>
<body>
<h1>{title}</h1>
{body}
<footer>Generated {generated_at}</footer>
</body>
</html>
"""


def render_page_html(record: dict) -> str:
    generated = datetime.fromisoformat(record["generated_at"])
    return _PAGE_TEMPLATE.format(
        title=escape(_entry_title(record["edition_label"], record["date_label"])),
        body=_record_body_html(record),
        generated_at=generated.strftime("%Y-%m-%d %H:%M %Z"),
    )


def _cdata(html: str) -> str:
    # Body text is already XML-escaped, so "]]>" can't occur — this is
    # a guard against future markup changes, not a live path.
    return "<![CDATA[" + html.replace("]]>", "]]&gt;") + "]]>"


def render_feed_xml(records: list[dict], *, base_url: str) -> str:
    """records must be newest-first and already capped."""
    items = []
    for rec in records:
        page_url = f"{base_url}/{rec['date']}-{rec['edition']}.html"
        pub = format_datetime(datetime.fromisoformat(rec["generated_at"]))
        items.append(
            "<item>\n"
            f"<title>{escape(_entry_title(rec['edition_label'], rec['date_label']))}</title>\n"
            f"<link>{escape(page_url)}</link>\n"
            f'<guid isPermaLink="true">{escape(page_url)}</guid>\n'
            f"<pubDate>{pub}</pubDate>\n"
            f"<description>{_cdata(_record_body_html(rec))}</description>\n"
            "</item>"
        )
    joined = "\n".join(items)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0">\n'
        "<channel>\n"
        f"<title>{escape(FEED_TITLE)}</title>\n"
        f"<link>{escape(base_url)}/</link>\n"
        f"<description>{escape(FEED_DESCRIPTION)}</description>\n"
        f"{joined}\n"
        "</channel>\n"
        "</rss>\n"
    )


def rebuild_feed(out_dir: Path, *, base_url: str) -> Path:
    """Scan the output dir and rewrite feed.xml, newest-first, capped
    at FEED_MAX_ENTRIES. Only {date}-{edition}.json records count;
    feed.xml, HTML pages, and anything else are ignored."""
    out_dir = Path(out_dir)
    records = []
    for p in sorted(out_dir.glob("*.json")):
        if not _NAME_RE.match(p.name):
            continue
        records.append(json.loads(p.read_text()))
    records.sort(
        key=lambda r: (r["date"], _EDITION_ORDER[r["edition"]]), reverse=True
    )
    records = records[:FEED_MAX_ENTRIES]
    feed_path = out_dir / "feed.xml"
    feed_path.write_text(render_feed_xml(records, base_url=base_url.rstrip("/")))
    return feed_path


def _make_record(
    *, iso_date: str, edition: str, edition_label: str, date_label: str,
    generated_at: datetime, digest: SlackDigest | None = None,
    headlines: list[dict] | None = None,
) -> dict:
    return {
        "date": iso_date,
        "edition": edition,
        "edition_label": edition_label,
        "date_label": date_label,
        "generated_at": generated_at.isoformat(),
        "degraded": digest is None,
        "digest": digest.model_dump() if digest else None,
        "headlines": headlines,
    }


def _publish_record(record: dict, *, out_dir: Path, base_url: str) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{record['date']}-{record['edition']}"
    (out_dir / f"{stem}.json").write_text(json.dumps(record, indent=2))
    page_path = out_dir / f"{stem}.html"
    page_path.write_text(render_page_html(record))
    rebuild_feed(out_dir, base_url=base_url)
    return page_path


def publish_digest(
    digest: SlackDigest, *, out_dir: Path, base_url: str, iso_date: str,
    edition: str, edition_label: str, date_label: str,
    generated_at: datetime,
) -> Path:
    record = _make_record(
        iso_date=iso_date, edition=edition, edition_label=edition_label,
        date_label=date_label, generated_at=generated_at, digest=digest,
    )
    return _publish_record(record, out_dir=out_dir, base_url=base_url)


def publish_fallback(
    articles: list[dict], *, out_dir: Path, base_url: str, iso_date: str,
    edition: str, edition_label: str, date_label: str,
    generated_at: datetime,
) -> Path:
    headlines = [
        {"link": a.get("link"), "title": a.get("title")} for a in articles
    ]
    record = _make_record(
        iso_date=iso_date, edition=edition, edition_label=edition_label,
        date_label=date_label, generated_at=generated_at,
        headlines=headlines,
    )
    return _publish_record(record, out_dir=out_dir, base_url=base_url)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_briefing_feed.py -v`
Expected: 6 PASS

- [ ] **Step 5: Run the full suite**

Run: `./.venv/bin/pytest -q`
Expected: 167 passed (161 baseline + 6 new)

- [ ] **Step 6: Commit**

```bash
git add jina_clone/briefing/feed.py tests/test_briefing_feed.py
git commit -m "feat(briefing): RSS feed + HTML page publishing for AI digest"
```

---

### Task 2: Orchestrator — publish seam replaces format+post

Rewrites `jobs/slack_digest.py` and its tests. **Note:** between this
commit and Task 3's, `python -m jina_clone slack-digest` is transiently
mis-wired (cli.py still passes the old kwargs). Tests stay green; do
not run the command until Task 3 lands.

**Files:**
- Rewrite: `jina_clone/jobs/slack_digest.py`
- Rewrite: `tests/test_jobs_slack_digest.py`

- [ ] **Step 1: Rewrite the tests (failing first)**

Replace the entire contents of `tests/test_jobs_slack_digest.py`:

```python
from pathlib import Path

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

    def __init__(self, rows=None, gen_fails=False, publish_fails=False):
        self.rows = _rows() if rows is None else rows
        self.gen_fails = gen_fails
        self.publish_fails = publish_fails
        self.fetch_kwargs: dict = {}
        self.published: list[tuple] = []
        self.notified: list[dict] = []

    async def fetch(self, pool, **kwargs):
        self.fetch_kwargs = kwargs
        return self.rows

    async def generate(self, *, articles, edition_label):
        if self.gen_fails:
            raise GeneratorFailure("claude -p exited 1")
        return _digest()

    def publish(self, digest):
        if self.publish_fails:
            raise OSError("disk full")
        self.published.append(("digest", digest))
        return Path("/tmp/2026-06-09-afternoon.html")

    def publish_fallback(self, articles):
        if self.publish_fails:
            raise OSError("disk full")
        self.published.append(("fallback", articles))
        return Path("/tmp/2026-06-09-afternoon.html")

    def notify_failure(self, **kwargs):
        self.notified.append(kwargs)

    async def run(self):
        return await run_slack_digest(
            None,
            window_hours=7.75,
            edition_label="Afternoon",
            title="AI/ML Slack Digest",
            ntfy_topic="fox-briefings",
            source_caps={"arXiv cs.AI": 2},
            fetch_articles=self.fetch,
            generate_digest=self.generate,
            publish=self.publish,
            publish_fallback=self.publish_fallback,
            notify_failure=self.notify_failure,
        )


async def test_happy_path_publishes_digest_no_notify():
    h = Harness()
    result = await h.run()
    assert h.published == [("digest", _digest())]
    assert h.notified == []
    assert result == {"degraded": False, "article_count": 2}


async def test_fetch_receives_window_caps_and_category():
    h = Harness()
    await h.run()
    assert h.fetch_kwargs["categories"] == ["ai"]
    assert h.fetch_kwargs["since_hours"] == 7.75
    assert h.fetch_kwargs["limit"] == 40
    assert h.fetch_kwargs["source_caps"] == {"arXiv cs.AI": 2}


async def test_llm_failure_publishes_fallback_and_notifies():
    h = Harness(gen_fails=True)
    result = await h.run()
    assert h.published == [("fallback", _rows())]
    assert len(h.notified) == 1
    assert "fallback" in h.notified[0]["reason"]
    assert result == {"degraded": True, "article_count": 2}


async def test_zero_articles_skips_publish_and_notify():
    h = Harness(rows=[])
    result = await h.run()
    assert result is None
    assert h.published == []
    assert h.notified == []


async def test_publish_failure_notifies_and_raises():
    h = Harness(publish_fails=True)
    with pytest.raises(OSError):
        await h.run()
    assert len(h.notified) == 1
    assert "publish" in h.notified[0]["reason"].lower()


async def test_degraded_plus_publish_failure_notifies_publish_only():
    h = Harness(gen_fails=True, publish_fails=True)
    with pytest.raises(OSError):
        await h.run()
    assert len(h.notified) == 1
    assert "publish" in h.notified[0]["reason"].lower()
    assert "fallback" not in h.notified[0]["reason"].lower()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `./.venv/bin/pytest tests/test_jobs_slack_digest.py -v`
Expected: FAIL — `TypeError: run_slack_digest() got an unexpected keyword argument 'publish'` (or missing `webhook_url`)

- [ ] **Step 3: Rewrite `jina_clone/jobs/slack_digest.py`**

Replace the entire file:

```python
"""Slack digest job: fetch AI articles → LLM digest → publish RSS feed.

Delivery is a public RSS feed Slack's /feed app polls — no app-install
rights in the work workspace, so no webhook/bot (2026-06-09 RSS spec).

Failure policy:
- LLM failure → publish a headlines-only fallback entry, then ntfy
  (degraded, not silent — the channel still gets links).
- Publish (file write) failure → ntfy, then re-raise so the cron log
  records it.
- Zero articles in window → no entry, no ntfy (quiet windows are normal).
"""
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

from jina_clone.briefing.generator import GeneratorFailure

log = logging.getLogger(__name__)


async def run_slack_digest(
    pool: Any,
    *,
    window_hours: float,
    edition_label: str,
    title: str,
    ntfy_topic: str | None,
    source_caps: dict[str, int] | None,
    fetch_articles: Callable[..., Awaitable[list[dict]]],
    generate_digest: Callable[..., Awaitable[Any]],
    publish: Callable[[Any], Path],
    publish_fallback: Callable[[list[dict]], Path],
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
    digest = None
    try:
        digest = await generate_digest(
            articles=articles, edition_label=edition_label,
        )
    except GeneratorFailure as err:
        log.error(
            "slack digest (%s): LLM failed, publishing headline fallback: %s",
            edition_label, err,
        )
        degraded = True

    try:
        page = publish_fallback(articles) if degraded else publish(digest)
    except Exception as err:
        notify_failure(
            topic=ntfy_topic, title=title,
            reason=f"Feed publish failed: {err}",
        )
        raise

    if degraded:
        notify_failure(
            topic=ntfy_topic, title=title,
            reason="LLM digest failed; published headlines-only fallback",
        )

    log.info(
        "slack digest (%s): published %s (%d candidates, degraded=%s)",
        edition_label, page, len(articles), degraded,
    )
    return {"degraded": degraded, "article_count": len(articles)}
```

- [ ] **Step 4: Run the tests to verify they pass, then the full suite**

Run: `./.venv/bin/pytest tests/test_jobs_slack_digest.py -v`
Expected: 6 PASS
Run: `./.venv/bin/pytest -q`
Expected: 167 passed

- [ ] **Step 5: Commit**

```bash
git add jina_clone/jobs/slack_digest.py tests/test_jobs_slack_digest.py
git commit -m "refactor(jobs): slack digest delivers via publish seam, not webhook post"
```

---

### Task 3: Settings + CLI rewiring

**Files:**
- Modify: `jina_clone/config.py` (`Settings` dataclass + `from_env`)
- Modify: `jina_clone/cli.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Replace the settings test (failing first)**

In `tests/test_config.py`, **delete** `test_settings_slack_webhook_url`
(lines ~103–116) and add in its place (`Path` and `pytest` are already
imported at the top of the file):

```python
def test_settings_feed_delivery(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("LLM_PROVIDER", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.delenv("FEED_BASE_URL", raising=False)
    monkeypatch.delenv("FEED_OUTPUT_DIR", raising=False)
    from jina_clone.config import Settings

    s = Settings.from_env()
    assert s.feed_base_url is None
    assert s.feed_output_dir == Path("feeds/ai-digest")

    monkeypatch.setenv("FEED_BASE_URL", "https://feeds.elucia.com/ai-digest")
    monkeypatch.setenv("FEED_OUTPUT_DIR", "/tmp/feeds")
    s = Settings.from_env()
    assert s.feed_base_url == "https://feeds.elucia.com/ai-digest"
    assert s.feed_output_dir == Path("/tmp/feeds")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./.venv/bin/pytest tests/test_config.py::test_settings_feed_delivery -v`
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'feed_base_url'`

- [ ] **Step 3: Swap the settings**

In `jina_clone/config.py`, `Settings` dataclass — **replace** the line

```python
    slack_webhook_url: str | None = None
```

with

```python
    feed_base_url: str | None = None
    feed_output_dir: Path = Path("feeds/ai-digest")
```

In `from_env`, **replace**

```python
            slack_webhook_url=os.getenv("SLACK_WEBHOOK_URL") or None,
```

with

```python
            feed_base_url=os.getenv("FEED_BASE_URL") or None,
            feed_output_dir=Path(os.getenv("FEED_OUTPUT_DIR", "feeds/ai-digest")),
```

Run: `./.venv/bin/pytest tests/test_config.py -v` → all 8 PASS

- [ ] **Step 4: Rewire the CLI**

In `jina_clone/cli.py`:

(a) Imports — at the top, **remove** `import json` (its only user was
the old dry-run printer) and add `import tempfile` to the stdlib block.
**Replace**

```python
from jina_clone.briefing import slack as briefing_slack
```

with

```python
from jina_clone.briefing import feed as briefing_feed
```

(b) Constants (~line 196) — update the comment above
`SLACK_DIGEST_WINDOWS` (values are unchanged):

```python
# Non-overlapping windows matching the cron cadence (8:45 / 16:30 ET —
# 15 min before the 9:00/16:45 channel targets, absorbing Slack's
# feed-poll lag): morning covers since yesterday 16:30, afternoon
# covers since 8:45.
SLACK_DIGEST_WINDOWS = {"morning": 16.25, "afternoon": 7.75}
```

(c) **Replace** the whole `_run_slack_digest` function:

```python
async def _run_slack_digest(settings: Settings, *, edition: str, dry_run: bool):
    if not settings.feed_base_url and not dry_run:
        raise SystemExit(
            "FEED_BASE_URL is required for slack-digest (set it in .env)"
        )
    cfg = load_briefing_config(settings.briefing_categories_file)

    tmp = None
    out_dir = settings.feed_output_dir
    if dry_run:
        tmp = tempfile.TemporaryDirectory(prefix="ai-digest-dryrun-")
        out_dir = Path(tmp.name)
    base_url = (settings.feed_base_url or "https://example.invalid/ai-digest").rstrip("/")

    iso_date = date.today().isoformat()
    edition_label = SLACK_DIGEST_EDITION_LABELS[edition]
    date_label = datetime.now().strftime("%a %b %-d")
    generated_at = datetime.now().astimezone()

    def publish(digest):
        return briefing_feed.publish_digest(
            digest, out_dir=out_dir, base_url=base_url, iso_date=iso_date,
            edition=edition, edition_label=edition_label,
            date_label=date_label, generated_at=generated_at,
        )

    def publish_fallback(articles):
        return briefing_feed.publish_fallback(
            articles, out_dir=out_dir, base_url=base_url, iso_date=iso_date,
            edition=edition, edition_label=edition_label,
            date_label=date_label, generated_at=generated_at,
        )

    briefing_generator.reset_usage()
    pool = await create_pool(settings.database_url)
    try:
        await run_slack_digest(
            pool,
            window_hours=SLACK_DIGEST_WINDOWS[edition],
            edition_label=edition_label,
            title=SLACK_DIGEST_TITLE,
            ntfy_topic=settings.ntfy_topic,
            source_caps=dict(cfg.source_caps),
            fetch_articles=fetch_section_articles,
            generate_digest=briefing_generator.generate_slack_digest,
            publish=publish,
            publish_fallback=publish_fallback,
            notify_failure=briefing_notify.notify_failure,
        )
        if dry_run:
            page = out_dir / f"{iso_date}-{edition}.html"
            if page.exists():
                print(page.read_text())
                print((out_dir / "feed.xml").read_text())
            else:
                print("(no articles in window — nothing rendered)")
    finally:
        if tmp is not None:
            tmp.cleanup()
        await pool.close()
        totals = briefing_generator.pop_usage_totals()
        if totals["calls"]:
            logging.info(
                "slack digest llm totals (%s): calls=%d input=%d output=%d "
                "cache_read=%d cache_creation=%d",
                edition,
                totals["calls"], totals["input"], totals["output"],
                totals["cache_read"], totals["cache_creation"],
            )
```

(d) In `main()`, update the two `slack-digest` help strings:

```python
    slack_p = sub.add_parser("slack-digest")
    slack_p.add_argument(
        "--edition", required=True, choices=["morning", "afternoon"],
        help="morning (8:45 ET, 16.25h window) or afternoon (16:30 ET, 7.75h window)",
    )
    slack_p.add_argument(
        "--dry-run", action="store_true",
        help="Print the rendered page HTML + feed XML to stdout; write nothing",
    )
```

The dispatch branch in `main()` is unchanged.

- [ ] **Step 5: Full suite + import smoke check**

Run: `./.venv/bin/pytest -q`
Expected: 167 passed
Run: `./.venv/bin/python -m jina_clone slack-digest --help`
Expected: usage text showing the new `--edition` / `--dry-run` help strings

- [ ] **Step 6: Commit**

```bash
git add jina_clone/config.py jina_clone/cli.py tests/test_config.py
git commit -m "feat(cli): slack-digest publishes RSS feed — FEED_BASE_URL/FEED_OUTPUT_DIR"
```

---

### Task 4: Webhook removal, docs, live E2E

**Files:**
- Delete: `jina_clone/briefing/slack.py`, `tests/test_briefing_slack.py`
- Modify: `.env.example`, `.gitignore`, `README.md`

- [ ] **Step 1: Delete the webhook module + tests**

```bash
git rm jina_clone/briefing/slack.py tests/test_briefing_slack.py
```

Then confirm nothing still references it:

Run: `grep -rn "briefing.slack\|briefing import slack\|SLACK_WEBHOOK_URL" jina_clone/ tests/`
Expected: no output

- [ ] **Step 2: `.env.example`**

**Replace** the trailing block

```
# Slack incoming webhook for the twice-daily AI/ML digest (slack-digest cmd)
SLACK_WEBHOOK_URL=
```

with

```
# Twice-daily AI/ML digest published as a public RSS feed the work
# Slack reads via /feed subscribe (slack-digest cmd).
# Public base URL nginx serves the output dir at, no trailing slash,
# e.g. https://feeds.elucia.com/ai-digest
FEED_BASE_URL=
# Where feed.xml + per-edition HTML/JSON are written (default feeds/ai-digest)
FEED_OUTPUT_DIR=
```

- [ ] **Step 3: `.gitignore`**

Add after the `briefings/tests/` line:

```
feeds/
```

- [ ] **Step 4: README**

**Replace** the body of the `## Slack AI/ML digest` section (keep the
heading) with:

````markdown
Twice-daily digest of `category: ai` articles, published as a public
RSS 2.0 feed + per-edition HTML pages (the work Slack workspace allows
no app installs, so the channel subscribes with
`/feed subscribe <FEED_BASE_URL>/feed.xml` instead of a webhook).
`FEED_BASE_URL` and `FEED_OUTPUT_DIR` live in `.env`; nginx serves the
output dir at the base URL. Each run writes a JSON record + HTML page
and rebuilds `feed.xml` (newest 20 entries, rebuild-by-scan).

```bash
./.venv/bin/python -m jina_clone slack-digest --edition=morning    # 8:45 ET cron
./.venv/bin/python -m jina_clone slack-digest --edition=afternoon  # 16:30 ET cron
./.venv/bin/python -m jina_clone slack-digest --edition=afternoon --dry-run  # print, don't write
```

Editions use non-overlapping windows (morning 16.25h, afternoon 7.75h),
so no article appears twice. On LLM failure the feed entry degrades to
headlines-only and sends an ntfy alert. Design:
`docs/superpowers/specs/2026-06-09-ai-digest-rss-feed-design.md`.
````

- [ ] **Step 5: Full suite**

Run: `./.venv/bin/pytest -q`
Expected: 159 passed (167 − 8 deleted webhook tests), 0 failures

- [ ] **Step 6: Live E2E (real DB + real claude -p, writes nothing)**

Per CLAUDE.md, run the real pipeline before polish. Reads production
`mcp_news` (read-only) and makes one real `claude -p` call:

Run: `./.venv/bin/python -m jina_clone slack-digest --edition=afternoon --dry-run`

Verify in the printed output:
- the HTML page: `<h1>AI/ML Afternoon Digest — <today>`, a `.lead`
  paragraph, 6–10 `<li><a href="…">` items with real article URLs,
  no double-escaped entities (`&amp;amp;`)
- the feed XML: one `<item>` whose `<link>`/`<guid>` end in
  `<today>-afternoon.html`, an RFC-822 `<pubDate>` with timezone
  offset, `<description><![CDATA[` present
- nothing written: `ls feeds/` → no such directory (dry-run used a
  temp dir)

If the digest content surprises (systematically <6 items, lead too
long), the prompt rules in `generator.py` were already tuned in the
webhook round — investigate before changing them.

- [ ] **Step 7: Commit**

```bash
git add .env.example .gitignore README.md
git commit -m "feat(digest): remove webhook delivery — RSS feed is the delivery path"
```

(The `git rm` from Step 1 is already staged and lands in this commit.)

---

## User setup checklist (manual, after Task 4)

Not automatable from this repo — walk the user through these:

1. **`.env`:** set `FEED_BASE_URL=https://feeds.elucia.com/ai-digest`
   (or chosen subdomain); `FEED_OUTPUT_DIR` only if non-default.
2. **DNS:** A record `feeds.elucia.com` → fox public IP.
3. **nginx** (pattern-match the existing elucia.com vhosts; no auth):

   ```nginx
   server {
       listen 80;
       server_name feeds.elucia.com;
       location /ai-digest/ {
           alias /home/elucia/dev/jina-clone/feeds/ai-digest/;
           autoindex off;
       }
   }
   ```

   `nginx -t` + reload, then `certbot --nginx -d feeds.elucia.com`.
4. **Permissions:** verify `www-data` can read the output dir
   (`o+x` on the home-dir path — known gotcha from the morningfox plan).
5. **One real publish:**
   `./.venv/bin/python -m jina_clone slack-digest --edition=afternoon`
   then `curl https://feeds.elucia.com/ai-digest/feed.xml`.
6. **Host crontab** (`crontab -e` as elucia; do NOT touch the two
   briefing lines):

   ```cron
   45 8  * * * cd /home/elucia/dev/jina-clone && ./.venv/bin/python -m jina_clone slack-digest --edition=morning   >> logs/slack-digest.log 2>&1
   30 16 * * * cd /home/elucia/dev/jina-clone && ./.venv/bin/python -m jina_clone slack-digest --edition=afternoon >> logs/slack-digest.log 2>&1
   ```

   ⚠️ `logs/` is root-owned on fox: `sudo touch logs/slack-digest.log
   && sudo chown elucia logs/slack-digest.log` before the first firing.
7. **In the work Slack channel:**
   `/feed subscribe https://feeds.elucia.com/ai-digest/feed.xml`
   and eyeball the first message (rendering of the CDATA description
   is the known unverifiable-until-now risk).

## Explicitly out of scope (from the spec)

- Voting/reactions/threading (dead with the bot-token path).
- Any change to the briefing pipeline (hard constraint).
- Pruning old HTML pages; feed auth; multiple categories/feeds.
