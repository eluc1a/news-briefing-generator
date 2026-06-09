# The Morning Fox — Website Launch (SP1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface the daily briefing on `themorningfox.com` via nginx, rendered from structured JSON, behind HTTP basic auth — without modifying any existing code.

**Architecture:** A new entry point (`run_web.py`) reuses the existing `run_briefing` orchestration but injects a `render` wrapper that, after rendering the PDF, also writes the briefing as JSON plus a manifest. A static page (`web/`) fetches the manifest and the newest edition's JSON and renders it as a responsive newspaper. nginx serves it under TLS with basic auth. **No existing `.py` file, test, or `.gitignore` is touched** — the implementation is purely additive, exploiting the `render` dependency-injection seam already present in `run_briefing`.

**Tech Stack:** Python 3.11, Pydantic v2, asyncpg, WeasyPrint (existing); vanilla HTML/CSS/JS (no build step); nginx + certbot (Let's Encrypt) on host `fox`.

**Hard constraint (from user):** Do not modify any existing code. New files only. The live daily-printed paper pipeline must not be put at risk.

---

## File Structure

**Created:**
- `jina_clone/briefing/web.py` — `publish_web_outputs`, `rebuild_index`, and the `make_render_and_publish` wrapper factory. Pure functions, no I/O beyond the briefings dir.
- `jina_clone/briefing/run_web.py` — new CLI entry point (`python -m jina_clone.briefing.run_web --edition=…`) that wires the existing `run_briefing` with the publish-aware render wrapper.
- `tests/test_briefing_web.py` — unit tests for `web.py`.
- `web/index.html` — page skeleton.
- `web/app.js` — fetch manifest + newest edition JSON, render sections.
- `web/style.css` — responsive newspaper styling.
- `web/fonts/` — copy of `BodoniModa-Regular.ttf` and `BodoniModa-Medium.ttf`.

**Not modified (verify at end):** `jina_clone/jobs/briefing.py`, `jina_clone/cli.py`, `jina_clone/briefing/renderer.py`, all existing tests, `.gitignore`.

**System/ops (on fox, not repo code):** `/etc/nginx/sites-available/themorningfox.com` (+ enabled symlink), `/etc/nginx/.htpasswd-morningfox`, certbot cert, host crontab edit, DNS A record.

---

## Task 1: `web.py` — JSON + manifest writer (TDD)

**Files:**
- Create: `jina_clone/briefing/web.py`
- Test: `tests/test_briefing_web.py`

Pattern note: tests in this repo use plain `pytest`. The `sample_briefing.json` fixture at `jina_clone/briefing/fixtures/sample_briefing.json` validates against `Briefing` (used by `test_briefing_renderer.py`), so load it the same way.

- [ ] **Step 1: Write the failing test**

Create `tests/test_briefing_web.py`:

```python
import json
from pathlib import Path

from jina_clone.briefing.schema import Briefing
from jina_clone.briefing.web import publish_web_outputs, rebuild_index

FIXTURE = Path(__file__).parent.parent / "jina_clone" / "briefing" / "fixtures" / "sample_briefing.json"


def _briefing() -> Briefing:
    return Briefing.model_validate_json(FIXTURE.read_text())


def test_publish_writes_edition_json(tmp_path):
    b = _briefing()
    publish_web_outputs(b, briefings_dir=tmp_path, iso_date="2026-06-05", edition="morning")

    out = tmp_path / "2026-06-05-morning.json"
    assert out.exists()
    # Round-trips back into a Briefing (byte-for-byte structured, not lossy).
    assert Briefing.model_validate_json(out.read_text()).title == b.title


def test_index_is_newest_first(tmp_path):
    b = _briefing()
    publish_web_outputs(b, briefings_dir=tmp_path, iso_date="2026-06-04", edition="morning")
    publish_web_outputs(b, briefings_dir=tmp_path, iso_date="2026-06-05", edition="morning")
    publish_web_outputs(b, briefings_dir=tmp_path, iso_date="2026-06-05", edition="evening")

    index = json.loads((tmp_path / "index.json").read_text())
    assert [(e["date"], e["edition"]) for e in index] == [
        ("2026-06-05", "evening"),
        ("2026-06-05", "morning"),
        ("2026-06-04", "morning"),
    ]
    top = index[0]
    assert top["json"] == "2026-06-05-evening.json"
    assert top["pdf"] == "2026-06-05-evening.pdf"
    assert top["title"] == "The Evening Fox"


def test_rebuild_index_ignores_unrelated_and_self(tmp_path):
    (tmp_path / "index.json").write_text("[]")
    (tmp_path / "notes.json").write_text("{}")
    (tmp_path / "2026-06-05-morning.json").write_text("{}")
    rebuild_index(tmp_path)

    index = json.loads((tmp_path / "index.json").read_text())
    assert [e["json"] for e in index] == ["2026-06-05-morning.json"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/bin/pytest tests/test_briefing_web.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jina_clone.briefing.web'`

- [ ] **Step 3: Implement `web.py`**

Create `jina_clone/briefing/web.py`:

```python
import json
import logging
import re
from pathlib import Path
from typing import Callable

from jina_clone.briefing.schema import Briefing

log = logging.getLogger(__name__)

EDITION_TITLES = {"morning": "The Morning Fox", "evening": "The Evening Fox"}

# Evening prints after morning, so it is "newer" within a day.
_EDITION_ORDER = {"morning": 0, "evening": 1}
_NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(morning|evening)\.json$")


def write_edition_json(
    briefing: Briefing, *, briefings_dir: Path, iso_date: str, edition: str
) -> Path:
    briefings_dir = Path(briefings_dir)
    briefings_dir.mkdir(parents=True, exist_ok=True)
    out = briefings_dir / f"{iso_date}-{edition}.json"
    out.write_text(briefing.model_dump_json(indent=2))
    return out


def rebuild_index(briefings_dir: Path) -> Path:
    """Scan the briefings dir and write a newest-first index.json.

    Rebuild-by-scan (not append) so the manifest self-heals when files
    are deleted or backfilled. Only files matching {date}-{edition}.json
    are included; index.json and anything else are ignored.
    """
    briefings_dir = Path(briefings_dir)
    entries = []
    for p in sorted(briefings_dir.glob("*.json")):
        m = _NAME_RE.match(p.name)
        if not m:
            continue
        d, edition = m.group(1), m.group(2)
        entries.append({
            "date": d,
            "edition": edition,
            "title": EDITION_TITLES[edition],
            "json": p.name,
            "pdf": f"{d}-{edition}.pdf",
        })
    entries.sort(key=lambda e: (e["date"], _EDITION_ORDER[e["edition"]]), reverse=True)
    index_path = briefings_dir / "index.json"
    index_path.write_text(json.dumps(entries, indent=2))
    return index_path


def publish_web_outputs(
    briefing: Briefing, *, briefings_dir: Path, iso_date: str, edition: str
) -> None:
    write_edition_json(briefing, briefings_dir=briefings_dir, iso_date=iso_date, edition=edition)
    rebuild_index(briefings_dir)


def make_render_and_publish(
    render_pdf: Callable[..., Path],
    *,
    briefings_dir: Path,
    edition: str,
) -> Callable[..., Path]:
    """Wrap an existing render_pdf callable so it ALSO writes the web
    JSON + manifest from the same Briefing. Web-publish failures are
    logged and swallowed — the printed paper is the primary product and
    must never be blocked by a website write.

    The returned callable matches the signature run_briefing expects for
    its `render` dependency: (briefing, pdf_path, *, generated_at, iso_date).
    """
    def render_and_publish(briefing, pdf_path, *, generated_at, iso_date):
        result = render_pdf(briefing, pdf_path, generated_at=generated_at, iso_date=iso_date)
        try:
            publish_web_outputs(
                briefing, briefings_dir=briefings_dir, iso_date=iso_date, edition=edition
            )
        except Exception as e:  # noqa: BLE001 — paper is primary; never abort on web failure
            log.warning("web publish failed (paper unaffected): %s", e)
        return result

    return render_and_publish
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/bin/pytest tests/test_briefing_web.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Add a test for the render wrapper**

Append to `tests/test_briefing_web.py`:

```python
from jina_clone.briefing.web import make_render_and_publish


def test_render_wrapper_publishes_and_returns_pdf(tmp_path):
    b = _briefing()
    calls = {}

    def fake_render(briefing, pdf_path, *, generated_at, iso_date):
        calls["pdf_path"] = pdf_path
        return pdf_path

    wrapper = make_render_and_publish(fake_render, briefings_dir=tmp_path, edition="morning")
    pdf = tmp_path / "2026-06-05-morning.pdf"
    result = wrapper(b, pdf, generated_at="08:10 ET", iso_date="2026-06-05")

    assert result == pdf
    assert calls["pdf_path"] == pdf
    assert (tmp_path / "2026-06-05-morning.json").exists()
    assert (tmp_path / "index.json").exists()


def test_render_wrapper_swallows_publish_failure(tmp_path):
    b = _briefing()
    sentinel = tmp_path / "out.pdf"

    def fake_render(briefing, pdf_path, *, generated_at, iso_date):
        return sentinel

    # Point publish at a path that cannot be created (a file used as a dir).
    bad = tmp_path / "afile"
    bad.write_text("x")
    wrapper = make_render_and_publish(fake_render, briefings_dir=bad, edition="morning")

    # Must NOT raise — returns the render result regardless.
    result = wrapper(b, sentinel, generated_at="08:10 ET", iso_date="2026-06-05")
    assert result == sentinel
```

- [ ] **Step 6: Run all web tests**

Run: `./.venv/bin/pytest tests/test_briefing_web.py -v`
Expected: PASS (5 passed)

- [ ] **Step 7: Commit**

```bash
git add jina_clone/briefing/web.py tests/test_briefing_web.py
git commit -m "feat(briefing): web.py — persist briefing JSON + manifest and render wrapper"
```

---

## Task 2: `run_web.py` — publish-aware entry point

**Files:**
- Create: `jina_clone/briefing/run_web.py`

This reuses the existing `run_briefing` verbatim, importing `cli.py`'s helpers rather than duplicating their bodies. The only behavioral difference vs `cli.py::_briefing_run` is `render=make_render_and_publish(...)` instead of `render=briefing_renderer.render_pdf`. Importing `jina_clone.cli` is safe — it has no module-level execution (its `main()` is only called under `if __name__`).

- [ ] **Step 1: Create `run_web.py`**

Create `jina_clone/briefing/run_web.py`:

```python
"""Web-publishing variant of `briefing run`.

Invoked by host cron instead of `python -m jina_clone briefing run`. It
reuses the existing run_briefing orchestration (emergency fallback, ntfy,
news_summaries logging) unchanged, but injects a render wrapper that also
writes the briefing JSON + index.json for themorningfox.com. Existing code
is not modified — this is an additive entry point.
"""
import argparse
import asyncio
import logging
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv

from jina_clone.briefing import generator as briefing_generator
from jina_clone.briefing import notify as briefing_notify
from jina_clone.briefing import printer as briefing_printer
from jina_clone.briefing import renderer as briefing_renderer
from jina_clone.briefing.config import load_briefing_config
from jina_clone.briefing.web import make_render_and_publish
from jina_clone.cli import (
    EDITION_TITLES,
    _make_markets_provider,
    _make_weather_provider,
    _setup_logging,
    _today_label,
    _volume_label,
)
from jina_clone.config import Settings
from jina_clone.jobs.briefing import run_briefing
from jina_clone.storage.db import create_pool, fetch_section_articles, insert_summary

log = logging.getLogger(__name__)


async def _run_web(settings: Settings, *, edition: str) -> None:
    cfg = load_briefing_config(settings.briefing_categories_file)
    title = EDITION_TITLES[edition]
    today = date.today()
    iso_date = today.isoformat()
    pdf_path = settings.briefings_dir / f"{iso_date}-{edition}.pdf"
    volume_label = f"{_volume_label(today)} · {edition.title()}"

    render = make_render_and_publish(
        briefing_renderer.render_pdf,
        briefings_dir=settings.briefings_dir,
        edition=edition,
    )

    briefing_generator.reset_usage()
    pool = await create_pool(settings.database_url)
    try:
        await run_briefing(
            pool=pool,
            config=cfg,
            window_hours=12,
            title=title,
            pdf_path=pdf_path,
            print_queue=settings.print_queue,
            ntfy_topic=settings.ntfy_topic,
            weather_provider=_make_weather_provider(settings),
            markets_provider=_make_markets_provider(settings),
            today_label=_today_label(),
            volume_label=volume_label,
            generated_at_label=datetime.now().strftime("%H:%M ET"),
            iso_date=iso_date,
            fetch_articles=fetch_section_articles,
            generate_front_matter=briefing_generator.generate_front_matter,
            generate_panel=briefing_generator.generate_panel,
            generate_briefs=briefing_generator.generate_briefs,
            render=render,
            print_pdf=briefing_printer.print_pdf,
            notify_printed=briefing_notify.notify_printed,
            notify_failure=briefing_notify.notify_failure,
            insert_summary=insert_summary,
            emergency_path=Path(__file__).parent / "fixtures" / "emergency.json",
        )
    finally:
        await pool.close()
        totals = briefing_generator.pop_usage_totals()
        if totals["calls"]:
            log.info(
                "briefing llm totals (%s %s): calls=%d input=%d output=%d "
                "cache_read=%d cache_creation=%d",
                iso_date, edition,
                totals["calls"], totals["input"], totals["output"],
                totals["cache_read"], totals["cache_creation"],
            )


def main() -> None:
    load_dotenv()
    _setup_logging()
    parser = argparse.ArgumentParser(prog="jina_clone.briefing.run_web")
    parser.add_argument("--edition", required=True, choices=["morning", "evening"])
    args = parser.parse_args()
    settings = Settings.from_env()
    asyncio.run(_run_web(settings, edition=args.edition))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify it imports and parses args without running the pipeline**

Run: `./.venv/bin/python -m jina_clone.briefing.run_web --help`
Expected: argparse usage text showing `--edition {morning,evening}`, exit 0. (Confirms all imports resolve and there is no module-level execution side effect.)

- [ ] **Step 3: Confirm existing tests still pass (no regressions from the new import graph)**

Run: `./.venv/bin/pytest tests/test_cli_briefing.py tests/test_jobs_briefing.py -v`
Expected: PASS (all existing briefing job/CLI tests green — they are unchanged).

- [ ] **Step 4: Commit**

```bash
git add jina_clone/briefing/run_web.py
git commit -m "feat(briefing): run_web entry point — reuse run_briefing with publish wrapper"
```

- [ ] **Step 5: Live E2E on fox (manual — produces a real edition)**

> Per CLAUDE.md, run a live E2E before building presentation on top of this output. This runs the real pipeline (LLM calls + prints the paper), so run it once intentionally.

Run: `cd /home/elucia/dev/jina-clone && ./.venv/bin/python -m jina_clone.briefing.run_web --edition=morning`
Expected:
- `briefings/<today>-morning.pdf` exists (paper printed as usual).
- `briefings/<today>-morning.json` exists and validates: `./.venv/bin/python -c "from jina_clone.briefing.schema import Briefing; import sys,glob; Briefing.model_validate_json(open(sorted(glob.glob('briefings/*-morning.json'))[-1]).read()); print('ok')"` prints `ok`.
- `briefings/index.json` exists with today's morning edition as entry `[0]`.

If the paper prints but the JSON/index are missing, check the `run_web` log line `web publish failed` — the wrapper swallows publish errors by design.

---

## Task 3: Static page + local E2E

**Files:**
- Create: `web/index.html`, `web/app.js`, `web/style.css`
- Create: `web/fonts/BodoniModa-Regular.ttf`, `web/fonts/BodoniModa-Medium.ttf` (copies)

- [ ] **Step 1: Copy the fonts**

```bash
mkdir -p web/fonts
cp jina_clone/briefing/static/fonts/BodoniModa-Regular.ttf web/fonts/
cp jina_clone/briefing/static/fonts/BodoniModa-Medium.ttf web/fonts/
```

- [ ] **Step 2: Create `web/index.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>The Morning Fox</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <main id="paper" aria-live="polite">
    <p id="status" class="status">Loading the latest edition…</p>
  </main>
  <script src="app.js"></script>
</body>
</html>
```

- [ ] **Step 3: Create `web/app.js`**

Renders the `Briefing` shape (see `jina_clone/briefing/schema.py`): `title, date, volume, location, weather{temp_high,temp_low,conditions,sunrise,sunset,daylight}, hourly{slots[]{time_label,temp_f,precip_pct}}, markets{items[]{symbol,value,change}}, lead{headline,deck,body,at_a_glance[]}, panels[]{section,lede_headline,lede_body,also[]{headline,body}}, pull_quote, briefs[]{topic,body}, data_point{value,context}, on_this_day{year_and_title,body}`.

```javascript
const EDITIONS = "/editions/";

const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};

function section(name) {
  const s = el("section");
  s.dataset.section = name;            // structural hook for future hover/click/reorder
  return s;
}

function renderMasthead(b) {
  const s = section("masthead");
  s.append(el("h1", "masthead-title", b.title));
  const sub = el("div", "masthead-sub");
  sub.append(el("span", null, b.volume), el("span", null, b.date), el("span", null, b.location));
  s.append(sub);
  return s;
}

function renderWeather(b) {
  const w = b.weather;
  const s = section("weather");
  s.append(el("span", "wx-cond", w.conditions));
  s.append(el("span", "wx-temp", `${w.temp_high}° / ${w.temp_low}°`));
  s.append(el("span", "wx-sun", `↑ ${w.sunrise}  ↓ ${w.sunset}  ${w.daylight}`));
  return s;
}

function renderMarkets(b) {
  const s = section("markets");
  for (const m of b.markets.items) {
    const item = el("div", "market");
    item.append(el("span", "mkt-sym", m.symbol), el("span", "mkt-val", m.value));
    if (m.change) item.append(el("span", "mkt-chg", m.change));
    s.append(item);
  }
  return s;
}

function renderLead(b) {
  const s = section("lead");
  s.append(el("h2", "lead-headline", b.lead.headline));
  s.append(el("p", "lead-deck", b.lead.deck));
  s.append(el("p", "lead-body", b.lead.body));
  const ul = el("ul", "at-a-glance");
  for (const g of b.lead.at_a_glance) ul.append(el("li", null, g));
  s.append(ul);
  return s;
}

function renderPanels(b) {
  const wrap = section("panels");
  for (const p of b.panels) {
    const panel = el("article", "panel");
    panel.dataset.panel = p.section;
    panel.append(el("h3", "panel-section", p.section));
    panel.append(el("h4", "panel-lede-headline", p.lede_headline));
    panel.append(el("p", "panel-lede-body", p.lede_body));
    for (const a of p.also) {
      const item = el("div", "panel-also");
      item.append(el("strong", null, a.headline), el("span", null, ` ${a.body}`));
      panel.append(item);
    }
    wrap.append(panel);
  }
  return wrap;
}

function renderPullQuote(b) {
  const s = section("pull-quote");
  s.append(el("blockquote", null, b.pull_quote));
  return s;
}

function renderBriefs(b) {
  const s = section("briefs");
  s.append(el("h3", "briefs-title", "In Brief"));
  for (const br of b.briefs) {
    const item = el("div", "brief");
    item.append(el("strong", null, br.topic), el("span", null, ` ${br.body}`));
    s.append(item);
  }
  return s;
}

function renderExtras(b) {
  const s = section("extras");
  const dp = el("div", "data-point");
  dp.append(el("span", "dp-value", b.data_point.value), el("span", "dp-context", b.data_point.context));
  const otd = el("div", "on-this-day");
  otd.append(el("strong", null, b.on_this_day.year_and_title), el("span", null, ` ${b.on_this_day.body}`));
  s.append(dp, otd);
  return s;
}

function renderDownload(entry) {
  const s = section("download");
  const a = el("a", "pdf-link", "Download the print edition (PDF)");
  a.href = EDITIONS + entry.pdf;
  s.append(a);
  return s;
}

function render(b, entry) {
  const paper = document.getElementById("paper");
  paper.replaceChildren(
    renderMasthead(b),
    renderWeather(b),
    renderMarkets(b),
    renderLead(b),
    renderPanels(b),
    renderPullQuote(b),
    renderBriefs(b),
    renderExtras(b),
    renderDownload(entry),
  );
}

function showStatus(msg) {
  document.getElementById("paper").replaceChildren(
    Object.assign(el("p", "status", msg))
  );
}

async function main() {
  try {
    const index = await (await fetch(EDITIONS + "index.json", { cache: "no-store" })).json();
    if (!Array.isArray(index) || index.length === 0) {
      showStatus("No briefing published yet. Check back after the next edition.");
      return;
    }
    const entry = index[0];
    const briefing = await (await fetch(EDITIONS + entry.json, { cache: "no-store" })).json();
    render(briefing, entry);
  } catch (e) {
    showStatus("Could not load the latest edition. Please try again shortly.");
    console.error(e);
  }
}

main();
```

- [ ] **Step 4: Create `web/style.css`**

```css
@font-face {
  font-family: 'Bodoni Moda';
  src: url('fonts/BodoniModa-Regular.ttf') format('truetype');
  font-weight: 400;
}
@font-face {
  font-family: 'Bodoni Moda';
  src: url('fonts/BodoniModa-Medium.ttf') format('truetype');
  font-weight: 500;
}

:root { --ink: #1a1a1a; --muted: #777; --rule: #1a1a1a; }

* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; color: var(--ink); background: #f7f5f0;
  font-family: Georgia, 'Times New Roman', serif; line-height: 1.5; }

#paper { max-width: 760px; margin: 0 auto; padding: 24px 18px 64px; background: #fffdf8; }

.status { text-align: center; color: var(--muted); padding: 48px 0; font-style: italic; }

section { margin: 0 0 22px; }

[data-section="masthead"] { border-bottom: 3px double var(--rule); padding-bottom: 10px; text-align: center; }
.masthead-title { font-family: 'Bodoni Moda', Georgia, serif; font-weight: 500;
  font-size: clamp(34px, 9vw, 56px); margin: 4px 0; letter-spacing: 0.5px; }
.masthead-sub { display: flex; gap: 14px; justify-content: center; flex-wrap: wrap;
  text-transform: uppercase; letter-spacing: 1px; font-size: 12px; color: var(--muted); }

[data-section="weather"] { display: flex; gap: 16px; flex-wrap: wrap; justify-content: center;
  font-size: 14px; border-bottom: 1px solid #ccc; padding-bottom: 12px; }
.wx-temp { font-weight: bold; }

[data-section="markets"] { display: flex; gap: 14px; flex-wrap: wrap; justify-content: center;
  font-size: 13px; border-bottom: 1px solid #ccc; padding-bottom: 12px; }
.market { display: flex; gap: 5px; align-items: baseline; }
.mkt-sym { font-weight: bold; } .mkt-chg { color: var(--muted); }

.lead-headline { font-family: 'Bodoni Moda', Georgia, serif; font-weight: 500;
  font-size: clamp(24px, 6vw, 34px); margin: 0 0 6px; line-height: 1.15; }
.lead-deck { font-style: italic; color: #333; margin: 0 0 10px; }
.at-a-glance { margin: 12px 0; padding-left: 20px; font-size: 14px; }

[data-section="panels"] { display: grid; gap: 20px; }
@media (min-width: 620px) { [data-section="panels"] { grid-template-columns: 1fr 1fr; } }
.panel { border-top: 2px solid var(--rule); padding-top: 8px; }
.panel-section { text-transform: uppercase; letter-spacing: 1px; font-size: 12px; color: var(--muted); margin: 0 0 6px; }
.panel-lede-headline { font-size: 18px; margin: 0 0 4px; }
.panel-also { font-size: 14px; margin: 6px 0; }

blockquote { font-family: 'Bodoni Moda', Georgia, serif; font-size: clamp(20px, 5vw, 26px);
  font-style: italic; text-align: center; border-top: 1px solid #ccc; border-bottom: 1px solid #ccc;
  padding: 16px 0; margin: 0; }

.briefs-title, .panel-section { font-weight: bold; }
.brief { font-size: 14px; margin: 6px 0; }

[data-section="extras"] { display: grid; gap: 12px; font-size: 13px; color: #333;
  border-top: 1px solid #ccc; padding-top: 12px; }
.dp-value { font-weight: bold; margin-right: 6px; }

.pdf-link { display: inline-block; margin-top: 8px; font-size: 14px; }
[data-section="download"] { text-align: center; border-top: 3px double var(--rule); padding-top: 14px; }
```

- [ ] **Step 5: Local E2E against the real sample fixture**

Set up a throwaway local editions dir from the committed fixture (the fixture validates as a `Briefing`):

```bash
mkdir -p web/editions
cp jina_clone/briefing/fixtures/sample_briefing.json web/editions/2026-06-05-morning.json
printf '[{"date":"2026-06-05","edition":"morning","title":"The Morning Fox","json":"2026-06-05-morning.json","pdf":"2026-06-05-morning.pdf"}]' > web/editions/index.json
cd web && ../.venv/bin/python -m http.server 8099
```

Open `http://localhost:8099/` in a browser. Verify every section renders: masthead with title/volume/date, weather strip, markets row, lead story + at-a-glance, four panels (two-column on wide screens, single on narrow), pull quote, briefs, extras, and the PDF download link. Resize to a narrow width and confirm it reflows to one column with no horizontal scroll.

Then stop the server (Ctrl-C) and remove the throwaway dir so it is not committed:

```bash
rm -rf web/editions
```

> `web/editions/` is a local test artifact only. In production nginx maps `/editions/` to the real `briefings/` dir via `alias` (Task 4); the page is not aware of the difference.

- [ ] **Step 6: Commit**

```bash
git add web/index.html web/app.js web/style.css web/fonts/
git commit -m "feat(web): static page that renders the latest briefing JSON"
```

---

## Task 4: nginx + basic auth + TLS on fox (ops)

> These run on host `fox`. They are system config, not repo code. Most steps need `sudo`. Suggest the user run privileged commands via the `! <command>` prompt prefix if Claude cannot sudo non-interactively.

**Files (on fox):**
- Create: `/etc/nginx/sites-available/themorningfox.com`
- Create: `/etc/nginx/.htpasswd-morningfox`
- Create symlink: `/etc/nginx/sites-enabled/themorningfox.com`

- [ ] **Step 1: DNS (user, at the registrar) — prerequisite**

Add an `A` record: `themorningfox.com` → fox's public IP (the same IP the existing `*.elucia.com` records resolve to). Add `www.themorningfox.com` as an `A` or `CNAME` to the apex. Wait for propagation before Step 5.

Verify: `dig +short themorningfox.com` returns fox's public IP.

- [ ] **Step 2: Create the basic-auth password file**

```bash
sudo sh -c 'printf "%s:%s\n" "fox" "$(openssl passwd -apr1 CHOSEN_PASSWORD)" > /etc/nginx/.htpasswd-morningfox'
sudo chmod 640 /etc/nginx/.htpasswd-morningfox
sudo chown root:www-data /etc/nginx/.htpasswd-morningfox
```

Replace `fox` (username) and `CHOSEN_PASSWORD` as desired. (Uses `openssl` since `apache2-utils`/`htpasswd` may not be installed; the existing box has `openssl`.)

- [ ] **Step 3: Create the HTTP (port-80) server block**

Create `/etc/nginx/sites-available/themorningfox.com` (HTTP only for now — certbot adds the 443 block in Step 5):

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name themorningfox.com www.themorningfox.com;

    root /home/elucia/dev/jina-clone/web;
    index index.html;

    auth_basic           "The Morning Fox";
    auth_basic_user_file /etc/nginx/.htpasswd-morningfox;

    location / {
        try_files $uri $uri/ =404;
    }

    location /editions/ {
        alias /home/elucia/dev/jina-clone/briefings/;
        autoindex off;
        types { application/json json; application/pdf pdf; }
        default_type application/octet-stream;
    }
}
```

- [ ] **Step 4: Enable the site and test config**

```bash
sudo ln -s /etc/nginx/sites-available/themorningfox.com /etc/nginx/sites-enabled/themorningfox.com
sudo nginx -t
```

Expected: `syntax is ok` / `test is successful`. Then: `sudo systemctl reload nginx`

- [ ] **Step 5: Issue the TLS certificate**

```bash
sudo certbot --nginx -d themorningfox.com -d www.themorningfox.com
```

Choose redirect-HTTP-to-HTTPS when prompted. certbot rewrites the site to add the `listen 443 ssl` block and an 80→443 redirect, matching the existing `*.elucia.com` pattern. Then: `sudo nginx -t && sudo systemctl reload nginx`

- [ ] **Step 6: Verify end to end**

Confirm nginx can read the served dirs (the `elucia` home dir must be traversable by `www-data`):

```bash
sudo -u www-data test -r /home/elucia/dev/jina-clone/web/index.html && echo "web readable"
sudo -u www-data test -r /home/elucia/dev/jina-clone/briefings/index.json && echo "editions readable"
```

If either fails, grant traversal: `chmod o+x /home/elucia /home/elucia/dev /home/elucia/dev/jina-clone` and ensure `web/` + `briefings/` are world-readable.

Then from any machine:

```bash
curl -u fox:CHOSEN_PASSWORD -I https://themorningfox.com/                       # 200, text/html
curl -u fox:CHOSEN_PASSWORD     https://themorningfox.com/editions/index.json   # the manifest JSON
curl -I https://themorningfox.com/                                              # 401 without credentials
```

Open `https://themorningfox.com/` in a browser, authenticate, and confirm the latest edition renders (this depends on Task 2's live E2E having produced at least one edition + index.json in `briefings/`).

- [ ] **Step 7: Switch host cron to the publishing entry point**

Edit the host crontab (`crontab -e` as `elucia`). Change the two briefing lines from:

```
10 8  * * * cd /home/elucia/dev/jina-clone && ./.venv/bin/python -m jina_clone briefing run --edition=morning >> logs/briefing.log 2>&1
10 20 * * * cd /home/elucia/dev/jina-clone && ./.venv/bin/python -m jina_clone briefing run --edition=evening >> logs/briefing.log 2>&1
```

to:

```
10 8  * * * cd /home/elucia/dev/jina-clone && ./.venv/bin/python -m jina_clone.briefing.run_web --edition=morning >> logs/briefing.log 2>&1
10 20 * * * cd /home/elucia/dev/jina-clone && ./.venv/bin/python -m jina_clone.briefing.run_web --edition=evening >> logs/briefing.log 2>&1
```

Verify: `crontab -l | grep run_web` shows both lines. The next scheduled run will publish the web edition automatically.

---

## Self-Review (completed)

- **Spec coverage:** Pipeline JSON + manifest → Task 1. Render-wrapper / no-existing-code seam → Task 1 (`make_render_and_publish`) + Task 2 (`run_web.py`). Web assets (index/app/style/fonts, semantic `data-section` blocks, graceful empty/error states, PDF link) → Task 3. nginx + basic auth + TLS + `/editions/` alias → Task 4. DNS prerequisite → Task 4 Step 1. Live E2E early → Task 2 Step 5 (pipeline) + Task 3 Step 5 (page). Crontab switch → Task 4 Step 7. All spec sections covered.
- **No-touch constraint:** Only new files are created/committed (`web.py`, `run_web.py`, `test_briefing_web.py`, `web/*`). `run_briefing`, `cli.py`, `renderer.py`, existing tests, and `.gitignore` are unmodified; Task 2 Step 3 re-runs existing tests to confirm no regression. New `briefings/*.json` artifacts are left untracked (not gitignored), per the spec's housekeeping note.
- **Type/name consistency:** `make_render_and_publish(render_pdf, *, briefings_dir, edition)` returns a callable with signature `(briefing, pdf_path, *, generated_at, iso_date) -> Path`, matching `run_briefing`'s `render(briefing, pdf_path, generated_at=..., iso_date=...)` call site (briefing.py:244). `publish_web_outputs(briefing, *, briefings_dir, iso_date, edition)` is consistent across Task 1 and Task 2. Manifest entry keys `{date, edition, title, json, pdf}` match between `rebuild_index` (Task 1) and `app.js`'s use of `entry.json` / `entry.pdf` (Task 3) and the nginx `/editions/` alias (Task 4).
- **Placeholders:** none — `CHOSEN_PASSWORD` and the htpasswd username are intentional user-supplied values, flagged inline.

---

## Out of scope (SP1)
- Source links / click-through (SP2 — needs `schema.py` + `generator.py` changes).
- Section reordering, hover affordances, location scrubbing (SP3).
- Edition toggle, archive browsing.
- Any change to the printed-PDF path or the `lp` print flow.
